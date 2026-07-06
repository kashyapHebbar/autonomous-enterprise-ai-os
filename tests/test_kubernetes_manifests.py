from __future__ import annotations

from pathlib import Path

from scripts.validate_kubernetes_manifests import validate_manifest_dir


def test_kubernetes_manifests_pass_local_validation():
    assert validate_manifest_dir(Path("deploy/kubernetes")) == []
