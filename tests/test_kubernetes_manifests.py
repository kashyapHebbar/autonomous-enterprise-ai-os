from __future__ import annotations

from pathlib import Path

from scripts.validate_kubernetes_manifests import validate_manifest_dir


def test_kubernetes_manifests_pass_local_validation():
    assert validate_manifest_dir(Path("deploy/kubernetes")) == []


def test_kubernetes_environment_overlays_pass_validation():
    for overlay in ["local", "staging", "production"]:
        assert validate_manifest_dir(Path("deploy/kubernetes/overlays") / overlay) == []
