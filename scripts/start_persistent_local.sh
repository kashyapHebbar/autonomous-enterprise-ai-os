#!/usr/bin/env bash
# Launch FastAPI, durable workflow queue worker, and monitoring scheduler.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
exec python scripts/launch_ai_os.py "$@"
