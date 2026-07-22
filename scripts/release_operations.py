from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

OVERLAY = Path("deploy/kubernetes/overlays/production")
REQUIRED_RENDER_VALUES = {
    "REPLACE_WITH_ACM_CERTIFICATE_ARN": "AEAI_ACM_CERTIFICATE_ARN",
    "REPLACE_WITH_ARTIFACT_BUCKET": "AEAI_ARTIFACT_BUCKET",
    "REPLACE_WITH_AWS_REGION": "AEAI_AWS_REGION",
    "REPLACE_WITH_OIDC_AUDIENCE": "AEAI_OIDC_AUDIENCE",
    "REPLACE_WITH_OIDC_ISSUER": "AEAI_OIDC_ISSUER",
    "REPLACE_WITH_OIDC_JWKS_URL": "AEAI_OIDC_JWKS_URL",
    "REPLACE_WITH_PRODUCTION_OTLP_ENDPOINT": "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT",
    "REPLACE_WITH_RUNTIME_SECRET_NAME": "AEAI_RUNTIME_SECRET_NAME",
    "REPLACE_WITH_WAF_ACL_ARN": "AEAI_WAF_ACL_ARN",
    "REPLACE_WITH_PUBLIC_HOSTNAME": "AEAI_PUBLIC_HOSTNAME",
    "ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:production": "AEAI_IMAGE_REFERENCE",
}


def render_production_manifest(template: str, env: Mapping[str, str]) -> str:
    rendered = template
    missing: list[str] = []
    for placeholder, env_name in REQUIRED_RENDER_VALUES.items():
        if placeholder not in rendered:
            continue
        value = str(env.get(env_name, "")).strip()
        if not value:
            missing.append(env_name)
        else:
            _validate_render_value(env_name, value)
            rendered = rendered.replace(placeholder, value)
    if missing:
        raise ValueError("Missing production render values: " + ", ".join(sorted(missing)))
    if "REPLACE_WITH_" in rendered:
        raise ValueError("Rendered manifest still contains production placeholders.")
    return rendered


def _validate_render_value(name: str, value: str) -> None:
    if name == "AEAI_IMAGE_REFERENCE" and not re.fullmatch(
        r"[a-zA-Z0-9./_-]+@sha256:[a-fA-F0-9]{64}", value
    ):
        raise ValueError("AEAI_IMAGE_REFERENCE must use an immutable sha256 digest.")
    if name == "AEAI_PUBLIC_HOSTNAME" and not re.fullmatch(
        r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value
    ):
        raise ValueError("AEAI_PUBLIC_HOSTNAME must be a DNS hostname without a scheme or path.")
    if name in {
        "AEAI_OIDC_ISSUER",
        "AEAI_OIDC_JWKS_URL",
        "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT",
    } and not value.startswith("https://"):
        raise ValueError(f"{name} must use HTTPS.")
    if name in {"AEAI_ACM_CERTIFICATE_ARN", "AEAI_WAF_ACL_ARN"} and not value.startswith(
        "arn:aws:"
    ):
        raise ValueError(f"{name} must be an AWS ARN.")


def run_command(command: Sequence[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ""


def build_manifest(env: Mapping[str, str]) -> str:
    template = run_command(["kubectl", "kustomize", str(OVERLAY)], capture=True)
    return render_production_manifest(template, env)


def deploy(env: Mapping[str, str]) -> None:
    manifest = build_manifest(env)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8") as handle:
        handle.write(manifest)
        handle.flush()
        run_command(["kubectl", "apply", "-f", handle.name])
    _wait_for_rollouts()


def rollback() -> None:
    for deployment_name in ("aeai-api", "aeai-worker"):
        run_command(
            ["kubectl", "-n", "aeai-os", "rollout", "undo", f"deployment/{deployment_name}"]
        )
    _wait_for_rollouts()


def failure_drill(base_url: str, *, recovery_seconds: int) -> float:
    pod_name = run_command(
        [
            "kubectl",
            "-n",
            "aeai-os",
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=aeai-api",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture=True,
    ).strip()
    if not pod_name:
        raise RuntimeError("No API pod was available for the failure drill.")
    started = time.monotonic()
    run_command(["kubectl", "-n", "aeai-os", "delete", "pod", pod_name, "--wait=false"])
    deadline = started + recovery_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url.rstrip('/')}/health", timeout=3) as response:
                if response.status == 200:
                    run_command(
                        [
                            "kubectl",
                            "-n",
                            "aeai-os",
                            "rollout",
                            "status",
                            "deployment/aeai-api",
                            f"--timeout={recovery_seconds}s",
                        ]
                    )
                    return time.monotonic() - started
        except (URLError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(f"API did not recover within {recovery_seconds} seconds.")


def _wait_for_rollouts() -> None:
    for deployment_name in ("aeai-api", "aeai-worker"):
        run_command(
            [
                "kubectl",
                "-n",
                "aeai-os",
                "rollout",
                "status",
                f"deployment/{deployment_name}",
                "--timeout=10m",
            ]
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy, roll back, and drill production releases."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render")
    subparsers.add_parser("deploy")
    subparsers.add_parser("rollback")
    drill = subparsers.add_parser("failure-drill")
    drill.add_argument("--base-url", required=True)
    drill.add_argument("--recovery-seconds", type=int, default=120)
    drill.add_argument("--confirm-production-impact", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "render":
            print(build_manifest(os.environ))
        elif args.command == "deploy":
            deploy(os.environ)
        elif args.command == "rollback":
            rollback()
        else:
            if not args.confirm_production_impact:
                raise ValueError("Failure drills require --confirm-production-impact.")
            recovery = failure_drill(args.base_url, recovery_seconds=args.recovery_seconds)
            print(f"Failure drill passed; API recovery observed in {recovery:.2f} seconds.")
    except (ValueError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
