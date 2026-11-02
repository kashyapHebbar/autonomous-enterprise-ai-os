"""Hugging Face-only Upgrade 5 tests. Real provider calls are mocked."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.planner import PlannerAgent
from aeai_os.api.app import create_app
from aeai_os.data.profiling import profile_csv_dataset
from aeai_os.llm.briefing import generate_briefing, render_briefing_html
from aeai_os.llm.gateway import HuggingFaceChatGateway, LLMError, build_llm_gateway
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import AppSettings, get_settings


class FakeGateway:
    model = "Qwen/Qwen3-32B"

    def __init__(self, *, fail: bool = False, recipe: str = "procurement"):
        self.calls = []
        self.fail = fail
        self.recipe = recipe

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise LLMError("provider unavailable")
        if kwargs["schema_name"] == "enterprise_analysis_recommendation":
            return {
                "recipe": self.recipe,
                "goals": ["summary", "outliers"],
                "rationale": "Review supplier exposure.",
            }
        return {
            "headline": "Spending deserves closer review",
            "executive_summary": "The analysis highlights concentration and review opportunities.",
            "observations": ["A small supplier group dominates the recorded activity."],
            "limitations": ["Confirm flagged patterns against supporting invoices."],
        }


def fake_opener(response: dict, requests: list):
    class FakeHttpResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(response).encode()

    def opener(request, *, timeout):
        requests.append((request, timeout))
        return FakeHttpResponse()

    return opener


def test_huggingface_gateway_fixed_endpoint_and_strict_json_schema():
    requests = []
    gateway = HuggingFaceChatGateway(
        api_key="hf_dummy_testing_only",
        model="Qwen/Qwen3-32B",
        timeout_seconds=30,
        opener=fake_opener(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"recipe":"generic"}'},
                    }
                ]
            },
            requests,
        ),
    )
    response = gateway.generate(
        instructions="Select a recipe",
        input_text="only column metadata",
        schema={
            "type": "object",
            "properties": {"recipe": {"type": "string"}},
            "required": ["recipe"],
            "additionalProperties": False,
        },
        schema_name="recipe_choice",
    )
    assert response == {"recipe": "generic"}
    request, timeout = requests[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://router.huggingface.co/v1/chat/completions"
    assert payload["model"] == "Qwen/Qwen3-32B"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == "only column metadata"
    assert "store" not in payload  # Responses API setting is not part of HF Chat Completions
    assert timeout == 30
    assert request.headers["Authorization"] == "Bearer hf_dummy_testing_only"


def test_settings_require_hf_token_only_when_opted_in(monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "true")
    monkeypatch.setenv("HF_TOKEN", "hf_dummy")
    monkeypatch.setenv("OPENAI_API_KEY", "openai_key_must_not_be_used")
    monkeypatch.setenv("AEAI_HF_PLANNER_MODEL", "Qwen/Qwen3-32B:cheapest")
    monkeypatch.setenv("AEAI_HF_BRIEFING_MODEL", "deepseek-ai/DeepSeek-V3.2")
    settings = get_settings()
    assert settings.llm_provider == "huggingface"
    assert settings.llm_api_key == "hf_dummy"
    assert build_llm_gateway(settings, purpose="planner").model == "Qwen/Qwen3-32B:cheapest"
    assert build_llm_gateway(settings, purpose="briefing").model == "deepseek-ai/DeepSeek-V3.2"
    assert build_llm_gateway(AppSettings(llm_enabled=False)) is None
    with pytest.raises(LLMError, match="Hugging Face token"):
        build_llm_gateway(AppSettings(llm_enabled=True, llm_api_key=""))
    with pytest.raises(LLMError, match="Only Hugging Face"):
        build_llm_gateway(
            AppSettings(llm_enabled=True, llm_provider="openai", llm_api_key="hf_abc")
        )


def test_gateway_rejects_unsafe_model_ids_and_does_not_echo_secret_errors():
    for model in ("https://internal.example/steal", "../etc/passwd", "Qwen/model?abc=1"):
        with pytest.raises(LLMError):
            HuggingFaceChatGateway(api_key="hf_secret", model=model)

    def failing_opener(_request, *, timeout):
        raise HTTPError("https://router.huggingface.co", 403, "secret echoed", None, None)

    gateway = HuggingFaceChatGateway(api_key="hf_secret", opener=failing_opener)
    with pytest.raises(LLMError) as info:
        gateway.generate(
            instructions="Return JSON",
            input_text="safe input",
            schema={"type": "object", "properties": {}, "required": []},
            schema_name="test_schema",
        )
    assert "403" in str(info.value)
    assert "hf_secret" not in str(info.value)
    assert "secret echoed" not in str(info.value)


def test_gateway_rejects_truncated_and_non_json_output():
    for message in (
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "hello"}}]},
        {"choices": []},
    ):
        gateway = HuggingFaceChatGateway(
            api_key="hf_test",
            opener=fake_opener(message, []),
        )
        with pytest.raises(LLMError):
            gateway.generate(
                instructions="Return JSON",
                input_text="schema only",
                schema={"type": "object", "properties": {}, "required": []},
                schema_name="test_schema",
            )


def test_planner_preserves_validated_graph_and_assisted_goals():
    profile = profile_csv_dataset("examples/procurement_demo.csv")
    gateway = FakeGateway()
    planner = PlannerAgent(llm_gateway=gateway)
    plan, analysis_plan = planner.create_dynamic_plan(
        "run_123", "Analyze supplier spend for risks", profile, "artifact_1"
    )
    assert planner.last_plan_source == "llm"
    assert analysis_plan.recipe == "procurement"
    assert analysis_plan.goals == ["summary", "outliers"]
    assert [node.agent for node in plan.nodes] == [
        "data_retrieval",
        "analytics_code",
        "visualization",
        "report",
        "evaluation",
    ]
    assert "columns" in gateway.calls[0]["input_text"]
    assert "example_values" not in gateway.calls[0]["input_text"]


def test_planner_falls_back_on_failure_and_invalid_recipe():
    profile = profile_csv_dataset("examples/sales_demo.csv")
    for gateway in (FakeGateway(fail=True), FakeGateway(recipe="procurement")):
        planner = PlannerAgent(llm_gateway=gateway)
        plan, analysis_plan = planner.create_dynamic_plan(
            "run_123", "Analyze revenue by region", profile
        )
        assert planner.last_plan_source == "deterministic"
        assert planner.last_plan_warning is not None
        assert analysis_plan.recipe == "generic"
        assert len(plan.nodes) == 5


def test_briefing_html_sanitization_and_fabricated_number_rejection():
    gateway = FakeGateway()
    briefing = generate_briefing(
        {"analysis_type": "procurement", "insights": ["A pattern exists"]}, gateway
    )
    briefing["headline"] = "<script>alert('x')</script>"
    rendered = render_briefing_html(briefing, "Qwen/Qwen3-32B")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered

    class Fabricator(FakeGateway):
        def generate(self, **kwargs):
            payload = super().generate(**kwargs)
            payload["executive_summary"] = "Savings equal 999999%"
            return payload

    with pytest.raises(LLMError):
        generate_briefing({"insights": ["A pattern exists"]}, Fabricator())


def test_full_procurement_workflow_uses_hf_gateway_and_preserves_kpis(monkeypatch, tmp_path):
    gateway = FakeGateway()
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **kwargs: gateway)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **kwargs: gateway)
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend, supplier risks and dashboard",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    kpis = next(a for a in body["artifacts"] if a["type"] == "kpi_table")
    assert kpis["metadata"]["total_spend"] == 165962.5
    briefings = [a for a in body["artifacts"] if a["metadata"].get("edition") == "ai_briefing"]
    assert len(briefings) == 1
    assert briefings[0]["metadata"]["verified_numerically"] is False
    assert briefings[0]["metadata"]["llm_model"] == "Qwen/Qwen3-32B"
    assert briefings[0]["metadata"]["llm_provider"] == "huggingface"
    events = [e for e in repo.list_events(run["id"]) if e.node_id == "planner"]
    assert events[-1].payload["planner_source"] == "llm"
    assert events[-1].payload["planner_model"] == "Qwen/Qwen3-32B"
    assert events[-1].payload["planner_provider"] == "huggingface"
    schema_artifact = next(a for a in body["artifacts"] if a["type"] == "schema_profile")
    schema_data = client.get(f"/runs/{run['id']}/artifacts/{schema_artifact['id']}/content").json()
    assert schema_data["analysis_plan"]["goals"] == ["summary", "outliers"]
    assert body["evaluations"][0]["passed"] is True
    assert len(gateway.calls) == 2


def test_hf_outage_keeps_the_existing_deterministic_workflow(monkeypatch, tmp_path):
    gateway = FakeGateway(fail=True)
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **kwargs: gateway)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **kwargs: gateway)
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement supplier spend",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert not any(
        a["metadata"].get("edition") == "ai_briefing" for a in response.json()["artifacts"]
    )
