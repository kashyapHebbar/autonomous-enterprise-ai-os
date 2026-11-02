"""Bounded, opt-in Hugging Face Inference Providers chat completion gateway.

No OpenAI service, package or API key is used. Hugging Face provides a
wire-compatible chat API but the request goes only to router.huggingface.co.
Only caller-selected compact business metadata leaves the host, never raw CSVs.
All provider output is untrusted; planner/report validators run afterward.
"""

from __future__ import annotations

import json
import re
import ssl
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from aeai_os.settings import AppSettings, get_settings

_HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"
_MAX_BODY_BYTES = 512 * 1024
_MODEL_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?::(?:cheapest|fastest|preferred))?$"
)


class LLMError(RuntimeError):
    """Provider-neutral and non-sensitive inference failure summary."""


class StructuredLLMGateway(Protocol):
    model: str

    def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int = 1200,
    ) -> dict[str, Any]: ...


class HuggingFaceChatGateway:
    """HF-routed hosted inference; URL fixed to prevent configurable SSRF.

    The API uses the Hugging Face router's standard chat JSON envelope. Its
    compatibility with OpenAI-style wire formats does NOT contact OpenAI.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "Qwen/Qwen3-32B",
        timeout_seconds: int = 45,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not api_key.strip():
            raise LLMError("Hugging Face token (HF_TOKEN) is not configured.")
        if not _MODEL_ID.fullmatch(model.strip()):
            raise LLMError(
                "Expected a Hugging Face namespace/model ID, optionally with a routing policy."
            )
        self._token = api_key.strip()
        self.model = model.strip()
        self._timeout = max(1, min(int(timeout_seconds), 90))
        self._opener = opener

    def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int = 1200,
    ) -> dict[str, Any]:
        if len(input_text) > 15000:
            raise LLMError("Model input exceeds its compact-data budget.")
        if len(instructions) > 12000:
            raise LLMError("Model instructions exceed the configured limit.")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", schema_name):
            raise LLMError("Invalid JSON output schema name.")
        if schema.get("type") != "object" or len(json.dumps(schema)) > 12000:
            raise LLMError("Invalid or oversized JSON schema.")

        # Direct scripted calls are budgeted too when HF is explicitly enabled.
        # Workflow calls reuse the shared ContextVar tracker instead.
        from aeai_os.llm.budget import (
            BudgetPolicy,
            current_usage_tracker,
            llm_usage_scope,
        )

        tracker = current_usage_tracker()
        settings = get_settings()
        scope = (
            llm_usage_scope(f"direct_{uuid4().hex}", BudgetPolicy.from_settings(settings))
            if tracker is None and settings.llm_enabled
            else nullcontext()
        )
        with scope:
            return self._generate_with_usage(
                instructions=instructions,
                input_text=input_text,
                schema=schema,
                schema_name=schema_name,
                max_output_tokens=max_output_tokens,
            )

    def _generate_with_usage(
        self,
        *,
        instructions: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        from aeai_os.llm.budget import current_usage_tracker

        tracker = current_usage_tracker()
        output_cap = min(max(int(max_output_tokens), 200), 2400)
        if tracker is not None:
            output_cap = min(output_cap, tracker.policy.max_output_tokens)
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions + "\n/no_think\nReturn JSON only."},
                {"role": "user", "content": input_text},
            ],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": output_cap,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        reservation = (
            tracker.begin(
                purpose=(
                    "planner"
                    if schema_name == "enterprise_analysis_recommendation"
                    else "investigation"
                    if schema_name == "enterprise_investigation_checks"
                    else "investigation_followup"
                    if schema_name == "enterprise_investigation_followup"
                    else "evidence_review"
                    if schema_name == "enterprise_evidence_review"
                    else "run_question"
                    if schema_name == "enterprise_run_question_answer"
                    else "briefing"
                ),
                model=self.model,
                body=json.dumps(request_body, ensure_ascii=False),
                max_output_tokens=output_cap,
            )
            if tracker is not None
            else None
        )
        request = Request(
            _HF_CHAT_URL,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        usage = None
        succeeded = False
        try:
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read(_MAX_BODY_BYTES + 1)
            except HTTPError as exc:
                # Never expose response bodies, which can echo confidential input.
                raise LLMError(f"Hugging Face inference returned HTTP {exc.code}.") from None
            except (URLError, TimeoutError, OSError, ssl.SSLError):
                raise LLMError("Hugging Face inference is unavailable or timed out.") from None
            if len(raw) > _MAX_BODY_BYTES:
                raise LLMError("Hugging Face response exceeded the size limit.")
            try:
                reply = json.loads(raw)
                if not isinstance(reply, dict):
                    raise LLMError("Unexpected Hugging Face response envelope.")
                choices = reply.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise LLMError("Unexpected Hugging Face response choices.")
                choice = choices[0]
                if choice.get("finish_reason") not in (None, "stop"):
                    raise LLMError("Model response was truncated or filtered.")
                message = choice.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    raise LLMError("Model returned no JSON text.")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise LLMError("Model output is not a JSON object.")
                usage = reply.get("usage")
                succeeded = True
                return result
            except (ValueError, KeyError, TypeError, AttributeError):
                raise LLMError("Hugging Face returned invalid structured JSON.") from None
        finally:
            if tracker is not None and reservation is not None:
                tracker.finish(reservation, usage, succeeded=succeeded)


def build_llm_gateway(
    settings: AppSettings | None = None,
    *,
    purpose: str = "planner",
) -> HuggingFaceChatGateway | None:
    """Build a server-side gateway only when explicitly enabled.

    Distinct models can be configured for planning and business summaries.
    Defaults to one strong, currently HF-served open-weight model.
    """
    settings = settings or get_settings()
    if not settings.llm_enabled:
        return None
    if settings.llm_provider not in {"huggingface", "hf"}:
        raise LLMError("Only Hugging Face is supported in this Upgrade 5 edition.")
    if purpose not in {"planner", "briefing"}:
        raise LLMError("Unsupported model purpose.")
    model = (
        settings.llm_planner_model if purpose == "planner" else settings.llm_briefing_model
    ) or settings.llm_model
    return HuggingFaceChatGateway(
        api_key=settings.llm_api_key,
        model=model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
