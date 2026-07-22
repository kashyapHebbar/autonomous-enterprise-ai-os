from __future__ import annotations

from pathlib import Path

import yaml

from scripts.validate_kubernetes_manifests import validate_manifest_dir


def test_kubernetes_manifests_pass_local_validation():
    assert validate_manifest_dir(Path("deploy/kubernetes")) == []


def test_kubernetes_environment_overlays_pass_validation():
    for overlay in ["local", "staging", "production"]:
        assert validate_manifest_dir(Path("deploy/kubernetes/overlays") / overlay) == []


def test_production_overlay_defines_public_reliability_controls():
    root = Path("deploy/kubernetes/overlays/production")
    kustomization = yaml.safe_load((root / "kustomization.yaml").read_text(encoding="utf-8"))
    resources = set(kustomization["resources"])

    assert {
        "ingress.yaml",
        "api-hpa.yaml",
        "worker-hpa.yaml",
        "disruption-budgets.yaml",
        "network-policies.yaml",
        "service-monitor.yaml",
        "prometheus-rules.yaml",
        "external-secret.yaml",
    } <= resources

    ingress = yaml.safe_load((root / "ingress.yaml").read_text(encoding="utf-8"))
    annotations = ingress["metadata"]["annotations"]
    assert ingress["spec"]["ingressClassName"] == "alb"
    assert "alb.ingress.kubernetes.io/certificate-arn" in annotations
    assert "alb.ingress.kubernetes.io/wafv2-acl-arn" in annotations

    rules = yaml.safe_load((root / "prometheus-rules.yaml").read_text(encoding="utf-8"))
    alerts = [
        rule
        for group in rules["spec"]["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]
    assert all(alert["labels"]["owner"] for alert in alerts)
    assert all(alert["annotations"]["runbook_url"] for alert in alerts)


def test_application_workloads_use_restricted_container_security():
    for filename in ["api-deployment.yaml", "worker-deployment.yaml"]:
        deployment = yaml.safe_load(
            Path("deploy/kubernetes/base", filename).read_text(encoding="utf-8")
        )
        pod_spec = deployment["spec"]["template"]["spec"]
        container = pod_spec["containers"][0]

        assert pod_spec["automountServiceAccountToken"] is False
        assert pod_spec["securityContext"]["runAsNonRoot"] is True
        assert pod_spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_validator_rejects_overlay_that_references_ancestor_directory(tmp_path):
    overlay = tmp_path / "overlays" / "production"
    overlay.mkdir(parents=True)
    (overlay / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "resources:\n"
        "  - ../..\n",
        encoding="utf-8",
    )
    (tmp_path / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "resources:\n"
        "  - overlays/production\n",
        encoding="utf-8",
    )

    errors = validate_manifest_dir(overlay)

    assert any("ancestor directory" in error for error in errors)
