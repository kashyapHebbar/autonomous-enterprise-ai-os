from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    service_name: str = "autonomous-enterprise-ai-os"
    environment: str = "local"
    api_port: int = 8000
    artifact_root: str = "artifacts"
    artifact_storage_backend: str = "local"
    artifact_s3_bucket: str = ""
    artifact_s3_prefix: str = "aeai-artifacts"
    artifact_s3_endpoint_url: str = ""
    artifact_s3_region: str = ""
    artifact_s3_access_key_id: str = ""
    artifact_s3_secret_access_key: str = ""
    run_repository_backend: str = "memory"
    database_url: str = "postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os"
    workflow_queue_backend: str = "repository"
    workflow_execution_mode: str = "sync"
    procurement_workflow_max_attempts: int = 3
    workflow_queue_timeout_seconds: int = 300
    workflow_queue_key_prefix: str = "aeai:workflow"
    redis_url: str = "redis://redis:6379/0"
    auth_enabled: bool = False
    auth_mode: str = "local"
    auth_token_profiles: str = ""
    auth_local_user_id: str = "local-dev"
    auth_local_user_name: str = "Local Developer"
    auth_local_roles: str = "admin"
    auth_local_organization_id: str = "local-org"
    auth_local_workspace_ids: str = "default"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_roles_claim: str = "roles"
    oidc_organization_claim: str = "organization_id"
    oidc_workspaces_claim: str = "workspace_ids"
    run_repository_create_schema: bool = True
    secure_headers_enabled: bool = True
    max_request_body_bytes: int = 10 * 1024 * 1024
    hsts_max_age_seconds: int = 31_536_000
    llm_enabled: bool = False
    llm_provider: str = "huggingface"
    llm_model: str = "Qwen/Qwen3-32B"
    llm_planner_model: str = ""
    llm_briefing_model: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_timeout_seconds: int = 45
    # Upgrade 6: conservative, app-side per-workflow/monthly estimate budgets.
    llm_workflow_budget_usd: float = 0.05
    llm_monthly_budget_usd: float = 4.50
    llm_max_calls_per_run: int = 3
    llm_max_output_tokens: int = 1800
    llm_input_usd_per_million: float = 0.08
    llm_output_usd_per_million: float = 0.25
    llm_usage_ledger_path: str = "artifacts/llm_usage.jsonl"
    dynamic_reasoning_enabled: bool = False
    dynamic_reasoning_review_enabled: bool = False
    # Upgrade 8: optional one-round evidence-grounded follow-up investigation.
    reasoning_followups_enabled: bool = False
    reasoning_max_followup_checks: int = 2
    # Upgrade 9: explicit, user-triggered questions on completed runs.
    run_questions_enabled: bool = False
    run_questions_max_per_run: int = 20
    # Upgrade 10: new, governed calculations on completed local CSV runs.
    analyst_tools_enabled: bool = False
    analyst_tools_max_per_run: int = 15
    analyst_commentary_enabled: bool = True


def get_settings() -> AppSettings:
    return AppSettings(
        service_name=os.getenv("AEAI_SERVICE_NAME", "autonomous-enterprise-ai-os"),
        environment=os.getenv("AEAI_ENV", "local"),
        api_port=int(os.getenv("AEAI_API_PORT", "8000")),
        artifact_root=os.getenv("AEAI_ARTIFACT_ROOT", "artifacts"),
        artifact_storage_backend=os.getenv("AEAI_ARTIFACT_STORAGE_BACKEND", "local"),
        artifact_s3_bucket=os.getenv(
            "AEAI_ARTIFACT_S3_BUCKET",
            os.getenv("MINIO_BUCKET", ""),
        ),
        artifact_s3_prefix=os.getenv("AEAI_ARTIFACT_S3_PREFIX", "aeai-artifacts"),
        artifact_s3_endpoint_url=os.getenv(
            "AEAI_ARTIFACT_S3_ENDPOINT_URL",
            os.getenv("MINIO_ENDPOINT", ""),
        ),
        artifact_s3_region=os.getenv("AEAI_ARTIFACT_S3_REGION", ""),
        artifact_s3_access_key_id=get_env_secret(
            "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
            "MINIO_ACCESS_KEY",
        ),
        artifact_s3_secret_access_key=get_env_secret(
            "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
            "MINIO_SECRET_KEY",
        ),
        run_repository_backend=os.getenv("AEAI_RUN_REPOSITORY_BACKEND", "memory"),
        run_repository_create_schema=_parse_bool(
            os.getenv("AEAI_RUN_REPOSITORY_CREATE_SCHEMA"),
            default=True,
        ),
        database_url=get_env_secret(
            "AEAI_DATABASE_URL",
            default="postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os",
        ),
        workflow_queue_backend=os.getenv("AEAI_WORKFLOW_QUEUE_BACKEND", "repository"),
        workflow_execution_mode=os.getenv("AEAI_WORKFLOW_EXECUTION_MODE", "sync"),
        procurement_workflow_max_attempts=int(
            os.getenv("AEAI_PROCUREMENT_WORKFLOW_MAX_ATTEMPTS", "3")
        ),
        workflow_queue_timeout_seconds=int(os.getenv("AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS", "300")),
        workflow_queue_key_prefix=os.getenv(
            "AEAI_WORKFLOW_QUEUE_KEY_PREFIX",
            "aeai:workflow",
        ),
        redis_url=os.getenv("AEAI_REDIS_URL", "redis://redis:6379/0"),
        auth_enabled=_parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False),
        auth_mode=os.getenv("AEAI_AUTH_MODE", "").strip().lower()
        or ("token" if _parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False) else "local"),
        auth_token_profiles=get_env_secret("AEAI_AUTH_TOKEN_PROFILES"),
        auth_local_user_id=os.getenv("AEAI_AUTH_LOCAL_USER_ID", "local-dev"),
        auth_local_user_name=os.getenv("AEAI_AUTH_LOCAL_USER_NAME", "Local Developer"),
        auth_local_roles=os.getenv("AEAI_AUTH_LOCAL_ROLES", "admin"),
        auth_local_organization_id=os.getenv("AEAI_AUTH_LOCAL_ORGANIZATION_ID", "local-org"),
        auth_local_workspace_ids=os.getenv("AEAI_AUTH_LOCAL_WORKSPACE_IDS", "default"),
        oidc_issuer=os.getenv("AEAI_OIDC_ISSUER", ""),
        oidc_audience=os.getenv("AEAI_OIDC_AUDIENCE", ""),
        oidc_jwks_url=os.getenv("AEAI_OIDC_JWKS_URL", ""),
        oidc_roles_claim=os.getenv("AEAI_OIDC_ROLES_CLAIM", "roles"),
        oidc_organization_claim=os.getenv("AEAI_OIDC_ORGANIZATION_CLAIM", "organization_id"),
        oidc_workspaces_claim=os.getenv("AEAI_OIDC_WORKSPACES_CLAIM", "workspace_ids"),
        secure_headers_enabled=_parse_bool(
            os.getenv("AEAI_SECURE_HEADERS_ENABLED"),
            default=True,
        ),
        max_request_body_bytes=int(os.getenv("AEAI_MAX_REQUEST_BODY_BYTES", str(10 * 1024 * 1024))),
        hsts_max_age_seconds=int(os.getenv("AEAI_HSTS_MAX_AGE_SECONDS", "31536000")),
        llm_enabled=_parse_bool(os.getenv("AEAI_LLM_ENABLED"), default=False),
        llm_provider=os.getenv("AEAI_LLM_PROVIDER", "huggingface").strip().lower(),
        llm_model=os.getenv("AEAI_LLM_MODEL", "Qwen/Qwen3-32B").strip(),
        llm_planner_model=os.getenv("AEAI_HF_PLANNER_MODEL", "").strip(),
        llm_briefing_model=os.getenv("AEAI_HF_BRIEFING_MODEL", "").strip(),
        llm_api_key=get_env_secret("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_API_TOKEN"),
        llm_timeout_seconds=int(os.getenv("AEAI_LLM_TIMEOUT_SECONDS", "45")),
        llm_workflow_budget_usd=float(os.getenv("AEAI_LLM_WORKFLOW_BUDGET_USD", "0.05")),
        llm_monthly_budget_usd=float(os.getenv("AEAI_LLM_MONTHLY_BUDGET_USD", "4.50")),
        llm_max_calls_per_run=int(os.getenv("AEAI_LLM_MAX_CALLS_PER_RUN", "3")),
        llm_max_output_tokens=int(os.getenv("AEAI_LLM_MAX_OUTPUT_TOKENS", "1800")),
        llm_input_usd_per_million=float(os.getenv("AEAI_HF_INPUT_USD_PER_MILLION", "0.08")),
        llm_output_usd_per_million=float(os.getenv("AEAI_HF_OUTPUT_USD_PER_MILLION", "0.25")),
        llm_usage_ledger_path=os.getenv("AEAI_LLM_USAGE_LEDGER_PATH", "artifacts/llm_usage.jsonl"),
        dynamic_reasoning_enabled=_parse_bool(
            os.getenv("AEAI_DYNAMIC_REASONING_ENABLED"),
            default=False,
        ),
        dynamic_reasoning_review_enabled=_parse_bool(
            os.getenv("AEAI_REASONING_REVIEW_ENABLED"),
            default=False,
        ),
        reasoning_followups_enabled=_parse_bool(
            os.getenv("AEAI_REASONING_FOLLOWUPS_ENABLED"),
            default=False,
        ),
        reasoning_max_followup_checks=int(os.getenv("AEAI_REASONING_MAX_FOLLOWUP_CHECKS", "2")),
        run_questions_enabled=_parse_bool(
            os.getenv("AEAI_RUN_QUESTIONS_ENABLED"),
            default=False,
        ),
        run_questions_max_per_run=int(os.getenv("AEAI_RUN_QUESTIONS_MAX_PER_RUN", "20")),
        analyst_tools_enabled=_parse_bool(
            os.getenv("AEAI_ANALYST_TOOLS_ENABLED"),
            default=False,
        ),
        analyst_tools_max_per_run=int(os.getenv("AEAI_ANALYST_TOOLS_MAX_PER_RUN", "15")),
        analyst_commentary_enabled=_parse_bool(
            os.getenv("AEAI_ANALYST_COMMENTARY_ENABLED"),
            default=True,
        ),
    )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_secret(
    *names: str,
    default: str = "",
    env: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if env is None else env
    for name in names:
        direct = values.get(name)
        if direct is not None and direct.strip():
            return direct.strip()
    for name in names:
        file_path = values.get(f"{name}_FILE")
        if file_path is None or not file_path.strip():
            continue
        path = Path(file_path.strip()).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return default
