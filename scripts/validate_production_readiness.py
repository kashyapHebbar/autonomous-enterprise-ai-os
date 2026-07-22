from __future__ import annotations

import sys
from pathlib import Path

import yaml

from scripts.validate_cloud_deployment import validate_cloud_deployment
from scripts.validate_kubernetes_manifests import validate_manifest_dir

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_OVERLAY = ROOT / "deploy/kubernetes/overlays/production"
REQUIRED_FILES = {
    ROOT / ".github/dependabot.yml",
    ROOT / ".github/workflows/security.yml",
    ROOT / ".github/workflows/production-readiness.yml",
    ROOT / "docs/operations/backup-and-recovery.md",
    ROOT / "docs/operations/incident-runbooks.md",
    ROOT / "docs/operations/production-readiness.md",
    ROOT / "docs/operations/readiness-evidence-template.md",
    ROOT / "docs/operations/security-validation.md",
    ROOT / "deploy/grafana/provisioning/dashboards/aeai-slo-dashboard.json",
    ROOT / "scripts/manage_recovery.py",
    ROOT / "scripts/production_readiness.py",
    ROOT / "scripts/release_operations.py",
}


def validate_production_readiness() -> list[str]:
    errors: list[str] = []
    for path in sorted(REQUIRED_FILES):
        if not path.exists():
            errors.append(f"Missing production readiness file: {path.relative_to(ROOT)}")

    errors.extend(validate_manifest_dir(PRODUCTION_OVERLAY))
    errors.extend(validate_cloud_deployment("aws"))

    ingress = _load_yaml(PRODUCTION_OVERLAY / "ingress.yaml")[0]
    annotations = ingress.get("metadata", {}).get("annotations", {})
    for annotation in [
        "alb.ingress.kubernetes.io/certificate-arn",
        "alb.ingress.kubernetes.io/ssl-policy",
        "alb.ingress.kubernetes.io/wafv2-acl-arn",
    ]:
        if annotation not in annotations:
            errors.append(f"Production ingress is missing annotation: {annotation}")

    for filename, minimum, maximum in [
        ("api-hpa.yaml", 3, 12),
        ("worker-hpa.yaml", 2, 20),
    ]:
        hpa = _load_yaml(PRODUCTION_OVERLAY / filename)[0]
        spec = hpa.get("spec", {})
        if spec.get("minReplicas") != minimum or spec.get("maxReplicas") != maximum:
            errors.append(f"{filename} must retain the reviewed scaling range.")

    rules = _load_yaml(PRODUCTION_OVERLAY / "prometheus-rules.yaml")[0]
    alerts = [
        rule
        for group in rules.get("spec", {}).get("groups", [])
        for rule in group.get("rules", [])
        if rule.get("alert")
    ]
    if len(alerts) < 4:
        errors.append("Production Prometheus rules must define at least four alerts.")
    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        if not labels.get("owner"):
            errors.append(f"Alert {alert['alert']} has no owner.")
        if not annotations.get("runbook_url"):
            errors.append(f"Alert {alert['alert']} has no runbook URL.")

    security_workflow = _read(ROOT / ".github/workflows/security.yml")
    for token in ["codeql-action", "pip-audit", "trivy-action"]:
        if token not in security_workflow:
            errors.append(f"Security workflow is missing {token}.")

    dockerfile = _read(ROOT / "Dockerfile")
    for token in ["USER 10001:10001", "PYTHONDONTWRITEBYTECODE=1"]:
        if token not in dockerfile:
            errors.append(f"Production container is missing hardening token: {token}")

    readiness_docs = _read(ROOT / "docs/operations/production-readiness.md")
    for token in ["99.9%", "RPO", "RTO", "Soak", "Rollback", "Failure injection"]:
        if token not in readiness_docs:
            errors.append(f"Production readiness docs are missing: {token}")
    return errors


def _load_yaml(path: Path) -> list[dict]:
    if not path.exists():
        return [{}]
    with path.open(encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if isinstance(document, dict)]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main() -> int:
    errors = validate_production_readiness()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Production readiness validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
