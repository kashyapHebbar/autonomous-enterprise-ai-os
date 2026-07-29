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
    "AEAI_ARTIFACT_STORAGE_BACKEND",
    "AEAI_ARTIFACT_S3_BUCKET",
    "AEAI_ARTIFACT_S3_PREFIX",
    "AEAI_ARTIFACT_S3_ENDPOINT_URL",
    "AEAI_ARTIFACT_S3_REGION",
    "AEAI_RUN_REPOSITORY_BACKEND",
    "AEAI_RUN_REPOSITORY_CREATE_SCHEMA",
    "AEAI_WORKFLOW_EXECUTION_MODE",
    "AEAI_WORKFLOW_QUEUE_BACKEND",
    "AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS",
    "AEAI_WORKFLOW_QUEUE_KEY_PREFIX",
    "AEAI_REDIS_URL",
    "AEAI_AUTH_ENABLED",
    "AEAI_SECURE_HEADERS_ENABLED",
    "AEAI_MAX_REQUEST_BODY_BYTES",
    "AEAI_HSTS_MAX_AGE_SECONDS",
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
    "AEAI_AUTH_TOKEN_PROFILES",
    "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
    "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
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

    documents, load_errors = _load_kustomized_documents(manifest_dir)
    errors.extend(load_errors)

    resource_map = {
        (str(document.get("kind")), str(document.get("metadata", {}).get("name"))): document
        for document in documents
    }
    required_resources = set(REQUIRED_RESOURCES)
    if manifest_dir.name == "production":
        required_resources -= {
            ("Secret", "aeai-secrets"),
            ("Deployment", "postgres"),
            ("Deployment", "redis"),
            ("Deployment", "minio"),
            ("Service", "postgres"),
            ("Service", "redis"),
            ("Service", "minio"),
        }
        required_resources.add(("ExternalSecret", "aeai-secrets"))
        forbidden_local_resources = {
            ("Secret", "aeai-secrets"),
            ("Deployment", "postgres"),
            ("Deployment", "redis"),
            ("Deployment", "minio"),
            ("Service", "postgres"),
            ("Service", "redis"),
            ("Service", "minio"),
        }
        errors.extend(
            f"production overlay must not include local resource: {kind}/{name}"
            for kind, name in sorted(forbidden_local_resources & set(resource_map))
        )
    missing = required_resources - set(resource_map)
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

    secret = resource_map.get(("Secret", "aeai-secrets"))
    if secret is not None:
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
        pod_spec = template.get("spec", {})
        init_containers = template.get("spec", {}).get("initContainers", [])
        if not any(
            container.get("name") == "validate-runtime-config"
            for container in init_containers
        ):
            errors.append(f"Deployment/{name} must define validate-runtime-config initContainer.")
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
        if "startupProbe" not in containers[0]:
            errors.append(f"Deployment/{name} must define a startupProbe.")
        if pod_spec.get("automountServiceAccountToken") is not False:
            errors.append(f"Deployment/{name} must disable service account token mounting.")
        pod_security = pod_spec.get("securityContext", {})
        if pod_security.get("runAsNonRoot") is not True:
            errors.append(f"Deployment/{name} must run as a non-root user.")
        if pod_security.get("seccompProfile", {}).get("type") != "RuntimeDefault":
            errors.append(f"Deployment/{name} must use the RuntimeDefault seccomp profile.")
        container_security = containers[0].get("securityContext", {})
        if container_security.get("allowPrivilegeEscalation") is not False:
            errors.append(f"Deployment/{name} must disable privilege escalation.")
        if container_security.get("readOnlyRootFilesystem") is not True:
            errors.append(f"Deployment/{name} must use a read-only root filesystem.")
        if "ALL" not in container_security.get("capabilities", {}).get("drop", []):
            errors.append(f"Deployment/{name} must drop all Linux capabilities.")
    return errors


def _load_kustomized_documents(manifest_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        documents = _collect_kustomization_documents(manifest_dir, seen=set())
    except ValueError as exc:
        return [], [str(exc)]
    return documents, errors


def _collect_kustomization_documents(
    manifest_dir: Path,
    *,
    seen: set[Path],
) -> list[dict[str, Any]]:
    resolved_dir = manifest_dir.resolve()
    if resolved_dir in seen:
        raise ValueError(f"kustomization recursion detected: {manifest_dir}")
    seen.add(resolved_dir)

    kustomization = _load_yaml_file(manifest_dir / "kustomization.yaml")
    resources = kustomization.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValueError(f"{manifest_dir}/kustomization.yaml must include resources.")

    documents: list[dict[str, Any]] = []
    for resource in resources:
        resource_path = manifest_dir / str(resource)
        if not resource_path.exists():
            raise ValueError(f"kustomization resource is missing: {resource_path}")
        if resource_path.is_dir():
            if resource_path.resolve() in resolved_dir.parents:
                raise ValueError(
                    "kustomization resource cannot reference an ancestor directory: "
                    f"{resource_path}"
                )
            documents.extend(_collect_kustomization_documents(resource_path, seen=seen))
        else:
            documents.extend(_load_yaml_documents(resource_path))

    patch_entries = [
        *(kustomization.get("patchesStrategicMerge") or []),
        *(kustomization.get("patches") or []),
    ]
    for patch_entry in patch_entries:
        patch_path = patch_entry.get("path") if isinstance(patch_entry, dict) else patch_entry
        if not patch_path:
            raise ValueError(f"Kustomization patch is missing a path: {manifest_dir}")
        for patch in _load_yaml_documents(manifest_dir / str(patch_path)):
            _apply_strategic_merge_patch(documents, patch)

    return documents


def _apply_strategic_merge_patch(
    documents: list[dict[str, Any]],
    patch: dict[str, Any],
) -> None:
    patch_kind = patch.get("kind")
    patch_metadata = patch.get("metadata", {})
    patch_name = patch_metadata.get("name")
    patch_namespace = patch_metadata.get("namespace")
    matches = [
        document
        for document in documents
        if document.get("kind") == patch_kind
        and document.get("metadata", {}).get("name") == patch_name
        and (
            patch_namespace is None
            or document.get("metadata", {}).get("namespace") == patch_namespace
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one patch target for {patch_kind}/{patch_name}, found {len(matches)}."
        )
    if patch.get("$patch") == "delete":
        documents.remove(matches[0])
    else:
        _merge_mapping(matches[0], patch)


def _merge_mapping(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key == "$patch":
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_mapping(target[key], value)
            continue
        if isinstance(value, list) and isinstance(target.get(key), list):
            target[key] = _merge_list(target[key], value)
            continue
        target[key] = value


def _merge_list(target: list[Any], patch: list[Any]) -> list[Any]:
    if all(isinstance(item, dict) and "name" in item for item in patch):
        merged = list(target)
        for patch_item in patch:
            for index, target_item in enumerate(merged):
                if (
                    isinstance(target_item, dict)
                    and target_item.get("name") == patch_item["name"]
                ):
                    updated = dict(target_item)
                    _merge_mapping(updated, patch_item)
                    merged[index] = updated
                    break
            else:
                merged.append(patch_item)
        return merged
    return patch


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
