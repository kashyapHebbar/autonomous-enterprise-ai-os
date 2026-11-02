#!/usr/bin/env bash
# Keep this running in a separate terminal; it is never started by the web app.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
export AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy
export AEAI_DATABASE_URL="${AEAI_DATABASE_URL:-sqlite:///artifacts/aeai-local-runs.db}"
export AEAI_RUN_REPOSITORY_CREATE_SCHEMA=true
export AEAI_LOCAL_SOURCE_CATALOG_PATH="${AEAI_LOCAL_SOURCE_CATALOG_PATH:-artifacts/aeai-local-sources.json}"
export AEAI_MONITOR_DB_PATH="${AEAI_MONITOR_DB_PATH:-artifacts/aeai-monitoring.db}"
export AEAI_LLM_ENABLED=false
exec python -m aeai_os.monitoring.worker --loop
