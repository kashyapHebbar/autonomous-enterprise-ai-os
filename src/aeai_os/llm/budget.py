"""Run-scoped LLM spend controls and durable local estimated-usage ledger.

This is an application-side, conservative estimate, NOT a Hugging Face billing
balance, card cap, or an exact token counter. It guards calls before dispatch.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from aeai_os.llm.gateway import LLMError

try:
    import fcntl  # POSIX file locks work across worker processes on macOS/Linux.
except ImportError:  # pragma: no cover - Windows is not the primary deployment target.
    fcntl = None


class LLMBudgetExceeded(LLMError):
    """The app skipped the inference request before sending business data."""


@dataclass(frozen=True)
class BudgetPolicy:
    workflow_usd: float = 0.05
    monthly_usd: float = 4.50
    max_calls: int = 3
    max_output_tokens: int = 1800
    input_usd_per_million: float = 0.08
    output_usd_per_million: float = 0.25
    ledger_path: str = "artifacts/llm_usage.jsonl"

    def __post_init__(self) -> None:
        if not 0 < self.workflow_usd <= 1000:
            raise ValueError("AI workflow budget must be positive and no more than $1,000.")
        if not 0 < self.monthly_usd <= 10000:
            raise ValueError("AI monthly budget must be positive and no more than $10,000.")
        if not 1 <= self.max_calls <= 100:
            raise ValueError("AI call limit must be between 1 and 100.")
        if not 200 <= self.max_output_tokens <= 2400:
            raise ValueError("AI output token cap must be between 200 and 2,400.")
        if not 0 < self.input_usd_per_million <= 100 or not 0 < self.output_usd_per_million <= 100:
            raise ValueError("AI estimate pricing must be positive and <= $100 per million tokens.")
        if not self.ledger_path.strip():
            raise ValueError("AI usage ledger path must not be empty.")

    @classmethod
    def from_settings(cls, settings: Any) -> BudgetPolicy:
        return cls(
            workflow_usd=settings.llm_workflow_budget_usd,
            monthly_usd=settings.llm_monthly_budget_usd,
            max_calls=settings.llm_max_calls_per_run,
            max_output_tokens=settings.llm_max_output_tokens,
            input_usd_per_million=settings.llm_input_usd_per_million,
            output_usd_per_million=settings.llm_output_usd_per_million,
            ledger_path=settings.llm_usage_ledger_path,
        )

    def price(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            max(0, prompt_tokens) * self.input_usd_per_million
            + max(0, completion_tokens) * self.output_usd_per_million
        ) / 1_000_000


# File lock ensures preflight reservations are serialized across uvicorn workers.
_LOCAL_LOCK = RLock()


class UsageLedger:
    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser()

    @contextmanager
    def _locked(self) -> Iterator[Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCAL_LOCK:
            with self.path.open("a+", encoding="utf-8") as stream:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    stream.seek(0)
                    yield stream
                finally:
                    if fcntl is not None:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _monthly_reserved(stream: Any, month: str) -> float:
        # Each request has a reserve entry and optionally a settlement entry.
        # Unsettled requests remain reserved after crashes: safer than overspend.
        costs: dict[str, float] = {}
        for line in stream:
            try:
                entry = json.loads(line)
                if entry.get("month") != month:
                    continue
                if entry.get("action") not in {"reserve", "settle"}:
                    continue
                request_id = entry["request_id"]
                amount = float(entry["cost_usd"])
                if 0 <= amount <= 10000 and isinstance(request_id, str):
                    costs[request_id] = amount
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                # If ledger is corrupt, conservatively disallow new requests.
                raise LLMBudgetExceeded(
                    "AI usage ledger cannot be verified; inference blocked."
                ) from None
        return sum(costs.values())

    @staticmethod
    def _append(stream: Any, entry: dict[str, Any]) -> None:
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    def reserve(
        self, request_id: str, run_id: str, month: str, estimate: float, cap: float
    ) -> None:
        try:
            with self._locked() as stream:
                total = self._monthly_reserved(stream, month)
                if total + estimate > cap + 1e-12:
                    raise LLMBudgetExceeded(
                        "App-side monthly AI cost budget reached; request not sent."
                    )
                self._append(
                    stream,
                    {
                        "action": "reserve",
                        "month": month,
                        "request_id": request_id,
                        "run_id": run_id,
                        "cost_usd": round(estimate, 9),
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
        except OSError:
            raise LLMBudgetExceeded("AI usage ledger unavailable; request not sent.") from None

    def settle(self, request_id: str, month: str, cost: float, source: str) -> None:
        try:
            with self._locked() as stream:
                self._append(
                    stream,
                    {
                        "action": "settle",
                        "month": month,
                        "request_id": request_id,
                        "cost_usd": round(cost, 9),
                        "usage_source": source,
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
        except OSError:
            # The original reserve stays in the ledger, preserving a conservative
            # monthly booked-cost total if persistence fails after a provider call.
            pass

    def month_total(self, month: str) -> float:
        try:
            with self._locked() as stream:
                return self._monthly_reserved(stream, month)
        except OSError:
            return 0.0  # Reporting only; reserve() fails closed.


@dataclass(frozen=True)
class RequestReservation:
    request_id: str
    month: str
    purpose: str
    model: str
    prompt_estimate: int
    max_output_tokens: int
    reserved_usd: float


@dataclass
class UsageTracker:
    run_id: str
    policy: BudgetPolicy
    ledger: UsageLedger = field(init=False)
    requests: int = 0
    blocked: int = 0
    completed: int = 0
    failed: int = 0
    billed_estimate_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    _reserved_run_usd: float = 0.0

    def __post_init__(self) -> None:
        self.ledger = UsageLedger(self.policy.ledger_path)

    def begin(
        self, *, purpose: str, model: str, body: str, max_output_tokens: int
    ) -> RequestReservation:
        if self.requests >= self.policy.max_calls:
            self._block(purpose, "max_calls")
            raise LLMBudgetExceeded("Maximum model calls per workflow reached; request not sent.")
        # Approximate prompt size using UTF-8, schema and formatting overhead.
        # Reservations use a safety margin; the provider usage field is preferred
        # for final accounting. Tokenization can vary by language and provider.
        prompt_estimate = max(1, (len(body.encode("utf-8")) + 2) // 3 + 128)
        reserve = self.policy.price(prompt_estimate, max_output_tokens)
        if self._reserved_run_usd + reserve > self.policy.workflow_usd + 1e-12:
            self._block(purpose, "workflow_budget")
            raise LLMBudgetExceeded("App-side workflow AI cost budget reached; request not sent.")
        request_id = f"llm_{uuid4().hex}"
        month = datetime.now(UTC).strftime("%Y-%m")
        try:
            self.ledger.reserve(request_id, self.run_id, month, reserve, self.policy.monthly_usd)
        except LLMBudgetExceeded:
            self._block(purpose, "monthly_budget_or_ledger")
            raise
        self.requests += 1
        self._reserved_run_usd += reserve
        return RequestReservation(
            request_id, month, purpose, model, prompt_estimate, max_output_tokens, reserve
        )

    def finish(self, reservation: RequestReservation, usage: Any, *, succeeded: bool) -> None:
        source = "provider" if isinstance(usage, dict) else "reserved_upper_estimate"
        if source == "provider":
            try:
                input_tokens = int(usage.get("prompt_tokens"))
                output_tokens = int(usage.get("completion_tokens"))
                if (
                    min(input_tokens, output_tokens) < 0
                    or max(input_tokens, output_tokens) > 10_000_000
                ):
                    raise ValueError("invalid counts")
                cost = self.policy.price(input_tokens, output_tokens)
            except (ValueError, TypeError, OverflowError):
                source = "reserved_upper_estimate"
        if source != "provider":
            input_tokens = reservation.prompt_estimate
            output_tokens = reservation.max_output_tokens
            cost = reservation.reserved_usd
        self.billed_estimate_usd += cost
        self.prompt_tokens += input_tokens
        self.completion_tokens += output_tokens
        if succeeded:
            self.completed += 1
        else:
            self.failed += 1
        self._reserved_run_usd += cost - reservation.reserved_usd
        self.ledger.settle(reservation.request_id, reservation.month, cost, source)
        self.calls.append(
            {
                "purpose": reservation.purpose,
                "model": reservation.model,
                "status": "completed" if succeeded else "provider_error",
                "input_units": input_tokens,
                "output_units": output_tokens,
                "usage_source": source,
                "estimated_cost_usd": round(cost, 8),
            }
        )

    def _block(self, purpose: str, reason: str) -> None:
        self.blocked += 1
        self.calls.append(
            {"purpose": purpose, "status": "blocked", "reason": reason, "estimated_cost_usd": 0.0}
        )

    def snapshot(self) -> dict[str, Any]:
        month = datetime.now(UTC).strftime("%Y-%m")
        return {
            "run_id": self.run_id,
            "provider": "huggingface",
            "model_calls": self.requests,
            "model_calls_completed": self.completed,
            "model_calls_failed": self.failed,
            "model_calls_blocked": self.blocked,
            "estimated_cost_usd": round(self.billed_estimate_usd, 8),
            "estimated_input_units": self.prompt_tokens,
            "estimated_output_units": self.completion_tokens,
            "workflow_budget_usd": self.policy.workflow_usd,
            "monthly_app_budget_usd": self.policy.monthly_usd,
            "month": month,
            "app_ledger_booked_usd": round(self.ledger.month_total(month), 8),
            "usage_note": "Estimates only; not the provider bill or Hugging Face credit balance.",
            "calls": list(self.calls),
        }


_CURRENT: ContextVar[UsageTracker | None] = ContextVar("aeai_llm_usage_tracker", default=None)


def current_usage_tracker() -> UsageTracker | None:
    return _CURRENT.get()


@contextmanager
def llm_usage_scope(run_id: str, policy: BudgetPolicy) -> Iterator[UsageTracker]:
    tracker = UsageTracker(run_id=run_id, policy=policy)
    token = _CURRENT.set(tracker)
    try:
        yield tracker
    finally:
        _CURRENT.reset(token)
