from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def assert_exists(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"Missing expected path: {path.relative_to(ROOT)}")


def main() -> int:
    expected_paths = [
        ROOT / "pyproject.toml",
        ROOT / "docker-compose.yml",
        ROOT / "Dockerfile",
        ROOT / "README.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "development.md",
        ROOT / "src" / "aeai_os" / "api",
        ROOT / "src" / "aeai_os" / "agents",
        ROOT / "src" / "aeai_os" / "orchestration",
        ROOT / "src" / "aeai_os" / "schemas",
        ROOT / "src" / "aeai_os" / "storage",
        ROOT / "src" / "aeai_os" / "evaluation",
        ROOT / "tests",
    ]

    for path in expected_paths:
        assert_exists(path)

    from aeai_os.api.health import build_health_payload

    payload = build_health_payload()
    if payload["status"] != "ok":
        raise AssertionError(f"Unexpected health status: {payload['status']}")

    components = {component["name"] for component in payload["components"]}
    for required in {"api", "orchestrator", "agent_registry", "artifact_store"}:
        if required not in components:
            raise AssertionError(f"Missing health component: {required}")

    print("Smoke check passed: scaffold and health payload are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

