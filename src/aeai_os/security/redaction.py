from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

SENSITIVE_KEY_FRAGMENTS = {
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "session",
    "token",
}

SENSITIVE_EXACT_KEYS = {
    "access_key",
    "access_key_id",
    "connection_string",
    "database_url",
    "dsn",
    "secret_access_key",
}

SAFE_REFERENCE_KEYS = {
    "configured_env_keys",
    "credential_profile",
    "credential_profile_id",
    "credential_profile_ids",
    "missing_env_keys",
    "secret_env_keys",
    "token_env_options",
}

URL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>'\"]+", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]{6,})")
KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b("
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|"
    r"authorization|password|passwd|secret|private[_-]?key|session[_-]?id"
    r")(\s*[:=]\s*)([^\s,;]+)"
)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Return a public-safe copy with secret-like fields redacted."""

    if key is not None and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): redact_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    if URL_PATTERN.fullmatch(value):
        return redact_uri(value)
    redacted = URL_PATTERN.sub(lambda match: redact_uri(match.group(0)), value)
    redacted = BEARER_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    return KEY_VALUE_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        redacted,
    )


def redact_uri(uri: str) -> str:
    parseable_uri = uri.replace(f"{REDACTED}@", "__aeai_redacted__@")
    try:
        parsed = urlsplit(parseable_uri)
    except ValueError:
        return uri
    netloc = parsed.netloc
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{REDACTED}@{host}{port}"
    query = urlencode(
        [
            (key, REDACTED if is_sensitive_key(key) else value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SAFE_REFERENCE_KEYS:
        return False
    if normalized in SENSITIVE_EXACT_KEYS:
        return True
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)
