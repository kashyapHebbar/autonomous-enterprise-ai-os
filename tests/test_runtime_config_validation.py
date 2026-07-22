from __future__ import annotations

from scripts.validate_runtime_config import validate_runtime_config


def test_runtime_config_accepts_staging_api_configuration():
    env = {
        "AEAI_ENV": "staging",
        "AEAI_SERVICE_NAME": "autonomous-enterprise-ai-os",
        "AEAI_API_PORT": "8000",
        "AEAI_RUN_REPOSITORY_BACKEND": "sqlalchemy",
        "AEAI_DATABASE_URL": "postgresql+psycopg://aeai:secret@postgres:5432/aeai_os",
        "AEAI_WORKFLOW_EXECUTION_MODE": "async",
        "AEAI_WORKFLOW_QUEUE_BACKEND": "redis",
        "AEAI_REDIS_URL": "redis://redis:6379/0",
        "AEAI_ARTIFACT_STORAGE_BACKEND": "minio",
        "AEAI_ARTIFACT_S3_BUCKET": "aeai-artifacts",
        "AEAI_ARTIFACT_S3_ACCESS_KEY_ID": "access-key",
        "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY": "secret-key",
        "AEAI_ARTIFACT_S3_ENDPOINT_URL": "http://minio:9000",
        "AEAI_AUTH_ENABLED": "true",
        "AEAI_AUTH_TOKEN_PROFILES": "admin-token=admin-1|Admin One|admin",
        "AEAI_TRACE_EXPORTER": "otlp_http",
        "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel:4318/v1/traces",
        "AEAI_SECURE_HEADERS_ENABLED": "true",
        "AEAI_MAX_REQUEST_BODY_BYTES": "10485760",
        "AEAI_HSTS_MAX_AGE_SECONDS": "31536000",
    }

    assert validate_runtime_config(env, component="api") == []


def test_runtime_config_rejects_missing_worker_queue_configuration():
    env = {
        "AEAI_ENV": "staging",
        "AEAI_SERVICE_NAME": "autonomous-enterprise-ai-os",
        "AEAI_API_PORT": "8000",
        "AEAI_RUN_REPOSITORY_BACKEND": "memory",
        "AEAI_WORKFLOW_EXECUTION_MODE": "sync",
        "AEAI_WORKFLOW_QUEUE_BACKEND": "repository",
        "AEAI_AUTH_ENABLED": "false",
        "AEAI_TRACE_EXPORTER": "none",
    }

    errors = validate_runtime_config(env, component="worker")

    assert "Worker requires AEAI_WORKFLOW_EXECUTION_MODE=async." in errors
    assert "Worker requires AEAI_WORKFLOW_QUEUE_BACKEND=redis." in errors


def test_runtime_config_accepts_oidc_identity_configuration():
    env = {
        "AEAI_ENV": "production",
        "AEAI_SERVICE_NAME": "autonomous-enterprise-ai-os",
        "AEAI_API_PORT": "8000",
        "AEAI_RUN_REPOSITORY_BACKEND": "sqlalchemy",
        "AEAI_DATABASE_URL": "postgresql+psycopg://aeai:secret@postgres/aeai_os",
        "AEAI_WORKFLOW_EXECUTION_MODE": "async",
        "AEAI_WORKFLOW_QUEUE_BACKEND": "redis",
        "AEAI_REDIS_URL": "redis://redis:6379/0",
        "AEAI_AUTH_MODE": "oidc",
        "AEAI_OIDC_ISSUER": "https://identity.example.com",
        "AEAI_OIDC_AUDIENCE": "aeai-os",
        "AEAI_OIDC_JWKS_URL": "https://identity.example.com/.well-known/jwks.json",
        "AEAI_SECURE_HEADERS_ENABLED": "true",
        "AEAI_MAX_REQUEST_BODY_BYTES": "10485760",
        "AEAI_HSTS_MAX_AGE_SECONDS": "31536000",
    }

    assert validate_runtime_config(env, component="api") == []


def test_runtime_config_rejects_production_placeholders():
    env = {
        "AEAI_ENV": "production",
        "AEAI_SERVICE_NAME": "autonomous-enterprise-ai-os",
        "AEAI_API_PORT": "8000",
        "AEAI_RUN_REPOSITORY_BACKEND": "sqlalchemy",
        "AEAI_DATABASE_URL": "REPLACE_WITH_PRODUCTION_DATABASE_URL",
        "AEAI_WORKFLOW_EXECUTION_MODE": "async",
        "AEAI_WORKFLOW_QUEUE_BACKEND": "redis",
        "AEAI_REDIS_URL": "redis://redis:6379/0",
        "AEAI_ARTIFACT_STORAGE_BACKEND": "s3",
        "AEAI_ARTIFACT_S3_BUCKET": "aeai-artifacts",
        "AEAI_ARTIFACT_S3_ACCESS_KEY_ID": "REPLACE_WITH_ACCESS_KEY",
        "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY": "REPLACE_WITH_SECRET_KEY",
        "AEAI_AUTH_ENABLED": "true",
        "AEAI_AUTH_TOKEN_PROFILES": "REPLACE_WITH_AUTH_TOKEN_PROFILES",
        "AEAI_TRACE_EXPORTER": "otlp_grpc",
        "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT": "REPLACE_WITH_OTLP_ENDPOINT",
        "AEAI_SECURE_HEADERS_ENABLED": "true",
        "AEAI_MAX_REQUEST_BODY_BYTES": "10485760",
        "AEAI_HSTS_MAX_AGE_SECONDS": "31536000",
    }

    errors = validate_runtime_config(env, component="api")

    assert any("AEAI_DATABASE_URL" in error for error in errors)
    assert any("AEAI_AUTH_TOKEN_PROFILES" in error for error in errors)
    assert any("AEAI_OTEL_EXPORTER_OTLP_ENDPOINT" in error for error in errors)
