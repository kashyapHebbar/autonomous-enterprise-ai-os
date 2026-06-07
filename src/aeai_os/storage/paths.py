from __future__ import annotations

from pathlib import Path


def run_artifact_dir(root: Path, run_id: str) -> Path:
    return root / "artifacts" / run_id


def artifact_path(root: Path, run_id: str, artifact_id: str, suffix: str) -> Path:
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return run_artifact_dir(root, run_id) / f"{artifact_id}{clean_suffix}"

