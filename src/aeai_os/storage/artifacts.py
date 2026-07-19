from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aeai_os.observability.tracing import start_span
from aeai_os.security.redaction import redact_value


class ArtifactStorageError(RuntimeError):
    """Raised when artifact payload storage cannot read or write content."""


class ArtifactStorageConfigurationError(ArtifactStorageError):
    """Raised when a configured artifact storage backend is incomplete."""


PUBLIC_DATASET_MAX_BYTES = 10 * 1024 * 1024
PUBLIC_DATASET_TIMEOUT_SECONDS = 10
PUBLIC_DATASET_CONTENT_TYPES = {
    "application/csv",
    "application/octet-stream",
    "text/csv",
    "text/plain",
}


@dataclass(frozen=True)
class StoredArtifact:
    uri: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactStore(Protocol):
    backend: str

    def write_bytes(
        self,
        run_id: str,
        node_id: str,
        filename: str,
        payload: bytes,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact: ...

    def read_bytes(self, uri: str) -> bytes: ...

    def local_path(self, uri: str) -> Path: ...

    def write_text(
        self,
        run_id: str,
        node_id: str,
        filename: str,
        payload: str,
        content_type: str = "text/plain; charset=utf-8",
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        return self.write_bytes(
            run_id=run_id,
            node_id=node_id,
            filename=filename,
            payload=payload.encode("utf-8"),
            content_type=content_type,
            metadata=metadata,
        )

    def write_json(
        self,
        run_id: str,
        node_id: str,
        filename: str,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        return self.write_text(
            run_id=run_id,
            node_id=node_id,
            filename=filename,
            payload=json.dumps(payload, indent=2, sort_keys=True),
            content_type="application/json",
            metadata=metadata,
        )

    def read_text(self, uri: str) -> str:
        return self.read_bytes(uri).decode("utf-8")

    def read_json(self, uri: str) -> dict[str, Any]:
        payload = json.loads(self.read_text(uri))
        if not isinstance(payload, dict):
            raise ArtifactStorageError(f"Artifact JSON payload must be an object: {uri}")
        return payload


class LocalArtifactStore(ArtifactStore):
    backend = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_bytes(
        self,
        run_id: str,
        node_id: str,
        filename: str,
        payload: bytes,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        with start_span(
            "artifact.write",
            _artifact_span_attributes(
                backend=self.backend,
                run_id=run_id,
                node_id=node_id,
                filename=filename,
                size_bytes=len(payload),
                content_type=content_type,
                credential_profile_id="local-filesystem",
            ),
        ):
            relative_path = _payload_relative_path(run_id, node_id, filename)
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return StoredArtifact(
                uri=str(path),
                metadata=_storage_metadata(
                    backend=self.backend,
                    key=relative_path.as_posix(),
                    size_bytes=len(payload),
                    content_type=content_type,
                    extra={"credential_profile_id": "local-filesystem", **dict(metadata or {})},
                ),
            )

    def read_bytes(self, uri: str) -> bytes:
        with start_span(
            "artifact.read",
            {"artifact.storage_backend": self.backend, "artifact.uri.scheme": _uri_scheme(uri)},
        ):
            return self.local_path(uri).read_bytes()

    def local_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme in {"", "file"}:
            return Path(parsed.path if parsed.scheme == "file" else uri)
        if parsed.scheme in {"http", "https"}:
            return _download_public_csv(uri, self.root / ".remote-cache")
        raise ArtifactStorageError(f"Local artifact store cannot read URI: {uri}")


class S3ArtifactStore(ArtifactStore):
    backend = "s3"

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        local_cache_root: str | Path = ".artifact-cache",
        client: Any | None = None,
    ) -> None:
        if not bucket.strip():
            raise ArtifactStorageConfigurationError(
                "S3 artifact storage requires AEAI_ARTIFACT_S3_BUCKET."
            )
        self.bucket = bucket.strip()
        self.prefix = _clean_prefix(prefix)
        self.endpoint_url = endpoint_url or None
        self.region_name = region_name or None
        self.local_cache_root = Path(local_cache_root)
        self._client = client or _build_boto3_client(
            endpoint_url=endpoint_url,
            region_name=region_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    def write_bytes(
        self,
        run_id: str,
        node_id: str,
        filename: str,
        payload: bytes,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        key = self._key(run_id, node_id, filename)
        with start_span(
            "artifact.write",
            _artifact_span_attributes(
                backend=self.backend,
                run_id=run_id,
                node_id=node_id,
                filename=filename,
                size_bytes=len(payload),
                content_type=content_type,
                credential_profile_id="artifact-s3-default",
                storage_key=key,
            ),
        ):
            request: dict[str, Any] = {
                "Bucket": self.bucket,
                "Key": key,
                "Body": payload,
                "Metadata": _object_metadata(metadata),
            }
            if content_type:
                request["ContentType"] = content_type
            self._client.put_object(**request)
            return StoredArtifact(
                uri=f"s3://{self.bucket}/{key}",
                metadata=_storage_metadata(
                    backend=self.backend,
                    key=key,
                    size_bytes=len(payload),
                    content_type=content_type,
                    extra={
                        "credential_profile_id": "artifact-s3-default",
                        "bucket": self.bucket,
                        "endpoint_url": self.endpoint_url,
                        **dict(metadata or {}),
                    },
                ),
            )

    def read_bytes(self, uri: str) -> bytes:
        with start_span(
            "artifact.read",
            {"artifact.storage_backend": self.backend, "artifact.uri.scheme": _uri_scheme(uri)},
        ):
            parsed = urlparse(uri)
            if parsed.scheme in {"", "file"}:
                return Path(parsed.path if parsed.scheme == "file" else uri).read_bytes()
            if parsed.scheme in {"http", "https"}:
                return _download_public_csv(uri, self.local_cache_root).read_bytes()
            if parsed.scheme != "s3":
                raise ArtifactStorageError(f"S3 artifact store cannot read URI: {uri}")
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            response = self._client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            return body.read() if hasattr(body, "read") else bytes(body)

    def local_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme in {"", "file"}:
            return Path(parsed.path if parsed.scheme == "file" else uri)
        if parsed.scheme in {"http", "https"}:
            return _download_public_csv(uri, self.local_cache_root)
        suffix = Path(parsed.path).suffix
        cache_name = sha256(uri.encode("utf-8")).hexdigest() + suffix
        cache_path = self.local_cache_root / cache_name
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(self.read_bytes(uri))
        return cache_path

    def _key(self, run_id: str, node_id: str, filename: str) -> str:
        relative_path = _payload_relative_path(run_id, node_id, filename).as_posix()
        return f"{self.prefix}/{relative_path}" if self.prefix else relative_path


def build_artifact_store(settings: Any, artifact_root: str | Path | None = None) -> ArtifactStore:
    local_root = artifact_root or getattr(settings, "artifact_root", "artifacts")
    backend = str(getattr(settings, "artifact_storage_backend", "local")).strip().lower()
    if backend in {"local", "filesystem", "file"}:
        return LocalArtifactStore(local_root)
    if backend in {"s3", "minio", "object", "object_storage"}:
        return S3ArtifactStore(
            bucket=getattr(settings, "artifact_s3_bucket", ""),
            prefix=getattr(settings, "artifact_s3_prefix", ""),
            endpoint_url=getattr(settings, "artifact_s3_endpoint_url", None),
            region_name=getattr(settings, "artifact_s3_region", None),
            access_key_id=getattr(settings, "artifact_s3_access_key_id", None),
            secret_access_key=getattr(settings, "artifact_s3_secret_access_key", None),
            local_cache_root=Path(local_root) / ".cache",
        )
    raise ArtifactStorageConfigurationError(f"Unsupported artifact storage backend: {backend}")


class _PublicHttpsRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        _validate_public_csv_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_public_csv(uri: str, cache_root: Path) -> Path:
    _validate_public_csv_url(uri)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{sha256(uri.encode('utf-8')).hexdigest()}.csv"
    if cache_path.exists():
        return cache_path

    request = Request(
        uri,
        headers={
            "Accept": "text/csv,text/plain;q=0.9,application/octet-stream;q=0.5",
            "User-Agent": "Autonomous-Enterprise-AI-OS/1.0",
        },
    )
    try:
        with build_opener(_PublicHttpsRedirectHandler()).open(
            request,
            timeout=PUBLIC_DATASET_TIMEOUT_SECONDS,
        ) as response:
            _validate_public_csv_url(response.geturl())
            content_type = response.headers.get_content_type().lower()
            if content_type not in PUBLIC_DATASET_CONTENT_TYPES:
                raise ArtifactStorageError(
                    f"Public dataset returned unsupported content type: {content_type}"
                )
            payload = response.read(PUBLIC_DATASET_MAX_BYTES + 1)
    except ArtifactStorageError:
        raise
    except OSError as exc:
        raise ArtifactStorageError(f"Unable to download public dataset: {exc}") from exc

    if len(payload) > PUBLIC_DATASET_MAX_BYTES:
        limit_mb = PUBLIC_DATASET_MAX_BYTES // (1024 * 1024)
        raise ArtifactStorageError(f"Public dataset exceeds the {limit_mb} MB limit.")
    if not payload.strip():
        raise ArtifactStorageError("Public dataset is empty.")

    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_bytes(payload)
    temporary_path.replace(cache_path)
    return cache_path


def _validate_public_csv_url(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme != "https":
        raise ArtifactStorageError("Public datasets must use HTTPS.")
    if not parsed.hostname:
        raise ArtifactStorageError("Public dataset URL must include a hostname.")
    if Path(parsed.path).suffix.lower() != ".csv":
        raise ArtifactStorageError("Public dataset URL must reference a .csv file.")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise ArtifactStorageError(
            f"Unable to resolve public dataset host: {parsed.hostname}"
        ) from exc
    if not addresses:
        raise ArtifactStorageError(
            f"Unable to resolve public dataset host: {parsed.hostname}"
        )
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ArtifactStorageError("Public dataset URL resolves to a non-public network address.")


def _payload_relative_path(run_id: str, node_id: str, filename: str) -> Path:
    return Path(_clean_path_segment(run_id)) / _clean_path_segment(node_id) / Path(filename).name


def _clean_path_segment(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in value.strip()
    )
    return cleaned or "unknown"


def _clean_prefix(prefix: str) -> str:
    return "/".join(part for part in prefix.strip("/").split("/") if part)


def _storage_metadata(
    backend: str,
    key: str,
    size_bytes: int,
    content_type: str | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "storage_backend": backend,
        "storage_key": key,
        "size_bytes": size_bytes,
    }
    if content_type:
        metadata["content_type"] = content_type
    metadata.update(redact_value(dict(extra or {})))
    return metadata


def _artifact_span_attributes(
    *,
    backend: str,
    run_id: str,
    node_id: str,
    filename: str,
    size_bytes: int,
    content_type: str | None,
    credential_profile_id: str,
    storage_key: str | None = None,
) -> dict[str, Any]:
    return {
        "run.id": run_id,
        "graph.node.id": node_id,
        "artifact.storage_backend": backend,
        "artifact.filename": Path(filename).name,
        "artifact.size_bytes": size_bytes,
        "artifact.content_type": content_type,
        "credential_profile.id": credential_profile_id,
        "artifact.storage_key": storage_key,
    }


def _uri_scheme(uri: str) -> str:
    return urlparse(uri).scheme or "file"


def _object_metadata(metadata: Mapping[str, Any] | None = None) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in redact_value(dict(metadata or {})).items()
        if value is not None
    }


def _build_boto3_client(
    endpoint_url: str | None,
    region_name: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise ArtifactStorageConfigurationError(
            "S3 artifact storage requires boto3. Install the storage extra with "
            "`pip install .[storage]`."
        ) from exc
    kwargs: dict[str, Any] = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region_name:
        kwargs["region_name"] = region_name
    if access_key_id:
        kwargs["aws_access_key_id"] = access_key_id
    if secret_access_key:
        kwargs["aws_secret_access_key"] = secret_access_key
    return boto3.client("s3", **kwargs)
