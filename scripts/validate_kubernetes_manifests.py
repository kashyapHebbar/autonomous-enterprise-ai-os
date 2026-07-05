from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_RESOURCES = {
    ("Namespace", "aeai-os"),
    ("ConfigMap", "aeai-config"),
    ("Secret", "aeai-secrets"),
    ("Deployment", "aeai-api"),
    ("Deployment", "aeai-worker"),
    ("Deployment", "postgres"),
    ("Deployment", "redis"),
    ("Deployment", "minio"),
    ("Service", "aeai-api"),
    ("Service", "postgres"),
    ("Service", "redis"),
    ("Service", "minio"),
}

REQUIRED_CONFIG_KEYS = {
    "AEAI_ENV",
    "AEAI_SERVICE_NAME",
    "AEAI_API_PORT",
    "AEAI_ARTIFACT_ROOT",
    "AEAI_RUN_REPOSITORY_BACKEND",
    "AEAI_TRACING_ENABLED",
    "AEAI_TRACE_EXPORTER",
    "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT",
    "AEAI_OTEL_EXPORTER_OTLP_INSECURE",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "REDIS_HOST",
    "REDIS_PORT",
    "MINIO_ENDPOINT",
    "MINIO_BUCKET",
}

REQUIRED_SECRET_KEYS = {
    "AEAI_DATABASE_URL",
    "POSTGRES_PASSWORD",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Kubernetes baseline manifests.")
    parser.add_argument(
        "manifest_dir",
        nargs="?",
        type=Path,
        default=Path("deploy/kubernetes"),
        help="Directory containing kustomization.yaml and Kubernetes manifests.",
    )
    args = parser.parse_args(argv)

    errors = validate_manifest_dir(args.manifest_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Kubernetes manifest validation passed: {args.manifest_dir}")
    return 0


def validate_manifest_dir(manifest_dir: Path) -> list[str]:
    errors: list[str] = []
    kustomization = _load_yaml_file(manifest_dir / "kustomization.yaml")
    resources = kustomization.get("resources")
    if not isinstance(resources, list) or not resources:
        return ["kustomization.yaml must include a non-empty resources list."]

    documents: list[dict[str, Any]] = []
    for resource in resources:
        resource_path = manifest_dir / str(resource)
        if not resource_path.exists():
            errors.append(f"kustomization resource is missing: {resource}")
            continue
        documents.extend(_load_yaml_documents(resource_path))

    resource_map = {
        (str(document.get("kind")), str(document.get("metadata", {}).get("name"))): document
        for document in documents
    }
    missing = REQUIRED_RESOURCES - set(resource_map)
    errors.extend(f"required resource is missing: {kind}/{name}" for kind, name in sorted(missing))

    for document in documents:
        metadata = document.get("metadata", {})
        namespace = metadata.get("namespace")
        if document.get("kind") != "Namespace" and namespace != "aeai-os":
            errors.append(
                f"{document.get('kind')}/{metadata.get('name')} must use namespace aeai-os."
            )

    config = resource_map.get(("ConfigMap", "aeai-config"), {})
    config_keys = set((config.get("data") or {}).keys())
    errors.extend(
        f"ConfigMap aeai-config missing key: {key}"
        for key in sorted(REQUIRED_CONFIG_KEYS - config_keys)
    )

    secret = resource_map.get(("Secret", "aeai-secrets"), {})
    secret_keys = set((secret.get("stringData") or {}).keys())
    errors.extend(
        f"Secret aeai-secrets missing key: {key}"
        for key in sorted(REQUIRED_SECRET_KEYS - secret_keys)
    )

    for deployment_name in ["aeai-api", "aeai-worker", "postgres", "redis", "minio"]:
        deployment = resource_map.get(("Deployment", deployment_name))
        if deployment is None:
            continue
        errors.extend(_validate_deployment(deployment))

    for service_name in ["aeai-api", "postgres", "redis", "minio"]:
        service = resource_map.get(("Service", service_name))
        if service is None:
            continue
        errors.extend(_validate_service(service))

    return errors


def _validate_deployment(deployment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = deployment["metadata"]["name"]
    selector_labels = deployment.get("spec", {}).get("selector", {}).get("matchLabels", {})
    template = deployment.get("spec", {}).get("template", {})
    template_labels = template.get("metadata", {}).get("labels", {})
    for key, value in selector_labels.items():
        if template_labels.get(key) != value:
            errors.append(f"Deployment/{name} selector label {key} does not match template.")

    containers = template.get("spec", {}).get("containers", [])
    if not containers:
        errors.append(f"Deployment/{name} must define at least one container.")
        return errors
    for container in containers:
        container_name = container.get("name", "<unnamed>")
        if not container.get("image"):
            errors.append(f"Deployment/{name} container {container_name} is missing image.")
        if "readinessProbe" not in container:
            errors.append(f"Deployment/{name} container {container_name} missing readinessProbe.")
        if "livenessProbe" not in container:
            errors.append(f"Deployment/{name} container {container_name} missing livenessProbe.")
        resources = container.get("resources", {})
        if "requests" not in resources or "limits" not in resources:
            errors.append(f"Deployment/{name} container {container_name} missing resources.")
    if name in {"aeai-api", "aeai-worker"}:
        env_sources = containers[0].get("envFrom", [])
        refs = {
            source.get("configMapRef", {}).get("name")
            or source.get("secretRef", {}).get("name")
            for source in env_sources
        }
        if "aeai-config" not in refs:
            errors.append(f"Deployment/{name} must load ConfigMap aeai-config.")
        if "aeai-secrets" not in refs:
            errors.append(f"Deployment/{name} must load Secret aeai-secrets.")
    return errors


def _validate_service(service: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = service["metadata"]["name"]
    if not service.get("spec", {}).get("selector"):
        errors.append(f"Service/{name} must define a selector.")
    if not service.get("spec", {}).get("ports"):
        errors.append(f"Service/{name} must expose at least one port.")
    return errors


def _load_yaml_file(path: Path) -> dict[str, Any]:
    documents = _load_yaml_documents(path)
    if len(documents) != 1:
        raise ValueError(f"Expected one YAML document in {path}.")
    return documents[0]


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError(f"YAML documents must be mappings: {path}")
    return documents


if __name__ == "__main__":
    raise SystemExit(main())
