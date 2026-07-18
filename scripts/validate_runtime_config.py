from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping

PLACEHOLDER_PREFIXES = ("change-me", "replace-me", "replace_with_", "todo")
PRODUCTION_ENVS = {"staging", "production", "prod"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate runtime environment before starting Kubernetes workloads."
    )
    parser.add_argument(
        "--component",
        choices=["api", "worker"],
        required=True,
        help="Workload component being validated.",
    )
    args = parser.parse_args(argv)

    errors = validate_runtime_config(os.environ, component=args.component)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Runtime configuration validation passed for {args.component}.")
    return 0


def validate_runtime_config(env: Mapping[str, str], *, component: str) -> list[str]:
    normalized_env = _value(env, "AEAI_ENV").lower()
    errors: list[str] = []
    required = {
        "AEAI_ENV",
        "AEAI_SERVICE_NAME",
        "AEAI_API_PORT",
        "AEAI_RUN_REPOSITORY_BACKEND",
        "AEAI_WORKFLOW_EXECUTION_MODE",
        "AEAI_WORKFLOW_QUEUE_BACKEND",
    }

    repository_backend = _value(env, "AEAI_RUN_REPOSITORY_BACKEND").lower()
    if repository_backend == "sqlalchemy":
        required.add("AEAI_DATABASE_URL")

    queue_backend = _value(env, "AEAI_WORKFLOW_QUEUE_BACKEND").lower()
    if queue_backend == "redis":
        required.add("AEAI_REDIS_URL")

    artifact_backend = _value(env, "AEAI_ARTIFACT_STORAGE_BACKEND").lower()
    if artifact_backend in {"s3", "minio", "object", "object_storage"}:
        required.update(
            {
                "AEAI_ARTIFACT_S3_BUCKET",
                "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
                "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
            }
        )
        if artifact_backend == "minio":
            required.add("AEAI_ARTIFACT_S3_ENDPOINT_URL")

    if _is_truthy(_value(env, "AEAI_AUTH_ENABLED")):
        required.add("AEAI_AUTH_TOKEN_PROFILES")

    trace_exporter = _value(env, "AEAI_TRACE_EXPORTER").lower()
    if trace_exporter in {"otlp_http", "otlp_grpc"}:
        required.add("AEAI_OTEL_EXPORTER_OTLP_ENDPOINT")

    if component == "worker":
        if _value(env, "AEAI_WORKFLOW_EXECUTION_MODE").lower() != "async":
            errors.append("Worker requires AEAI_WORKFLOW_EXECUTION_MODE=async.")
        if queue_backend != "redis":
            errors.append("Worker requires AEAI_WORKFLOW_QUEUE_BACKEND=redis.")

    for key in sorted(required):
        value = _value(env, key)
        if not value:
            errors.append(f"Missing required environment variable: {key}.")
            continue
        if normalized_env in PRODUCTION_ENVS and _is_placeholder(value):
            errors.append(f"Environment variable {key} still contains a placeholder value.")

    return errors


def _value(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "")).strip()


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return any(normalized.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
