"""Start FastAPI, workflow execution and monitoring as one supervised LOCAL stack.

This script is for single-host development. Production deployments should use
separately managed API/worker services backed by a shared database and storage.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def local_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    env.update(
        {
            "AEAI_RUN_REPOSITORY_BACKEND": "sqlalchemy",
            "AEAI_DATABASE_URL": env.get(
                "AEAI_DATABASE_URL", "sqlite:///artifacts/aeai-local-runs.db"
            ),
            "AEAI_RUN_REPOSITORY_CREATE_SCHEMA": "true",
            "AEAI_LOCAL_SOURCE_CATALOG_PATH": env.get(
                "AEAI_LOCAL_SOURCE_CATALOG_PATH", "artifacts/aeai-local-sources.json"
            ),
            "AEAI_MONITOR_DB_PATH": env.get("AEAI_MONITOR_DB_PATH", "artifacts/aeai-monitoring.db"),
            "AEAI_WORKFLOW_QUEUE_BACKEND": "repository",
            "AEAI_WORKFLOW_EXECUTION_MODE": "async",
            "AEAI_WORKFLOW_HEARTBEAT_PATH": env.get(
                "AEAI_WORKFLOW_HEARTBEAT_PATH", "artifacts/aeai-workflow-heartbeat.json"
            ),
        }
    )
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch all local AEAI services")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-monitoring", action="store_true", help="Disable scheduled monitoring worker"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    os.chdir(ROOT)
    (ROOT / "artifacts").mkdir(exist_ok=True)
    env = local_environment()
    # Forbid unsafe multi-process setups based on shared sqlite over a remote FS.
    if env.get("AEAI_ENV", "local").lower() in {"production", "prod"}:
        parser.error("Local launcher cannot be used for production; use managed process services")
    workers = {
        "workflow": [sys.executable, "scripts/managed_workflow_worker.py"],
        "risk": [sys.executable, "scripts/run_risk_worker.py", "--loop"],
    }
    if not args.no_monitoring:
        workers["monitoring"] = [sys.executable, "-m", "aeai_os.monitoring.worker", "--loop"]
    processes: dict[str, subprocess.Popen] = {}
    stop = False

    def shutdown(*_args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        api_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "aeai_os.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ]
        processes["api"] = subprocess.Popen(api_cmd, env=env, cwd=ROOT)
        for name, command in workers.items():
            child_env = dict(env)
            if name in {"monitoring", "risk"}:
                child_env["AEAI_LLM_ENABLED"] = "false"
            processes[name] = subprocess.Popen(command, env=child_env, cwd=ROOT)
        print(f"AEAI running at http://127.0.0.1:{args.port}/app", flush=True)
        print("All background workers are managed by this launcher. Ctrl+C stops all.", flush=True)
        while not stop:
            time.sleep(2)
            if processes["api"].poll() is not None:
                print("FastAPI exited. Shutting down workers.", file=sys.stderr, flush=True)
                return processes["api"].returncode or 1
            for name, command in workers.items():
                if processes[name].poll() is not None:
                    print(f"{name} worker exited; restarting…", flush=True)
                    child_env = dict(env)
                    if name in {"monitoring", "risk"}:
                        child_env["AEAI_LLM_ENABLED"] = "false"
                    processes[name] = subprocess.Popen(command, env=child_env, cwd=ROOT)
        return 0
    finally:
        for proc in processes.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in processes.values():
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
