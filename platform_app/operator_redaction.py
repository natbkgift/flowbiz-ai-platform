"""Server-side redaction for AI Operator UI payloads.

The operator console must never receive raw secrets, environment values,
service tokens, DB credentials, private keys, or certificates. This module
walks JSON payloads returned from core and replaces sensitive substrings or
fields before the data is forwarded to the browser.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED_PLACEHOLDER = "[REDACTED]"

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "privatekey",
    "credential",
    "client_secret",
)

SENSITIVE_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
    re.compile(r"id_rsa$", re.IGNORECASE),
    re.compile(r"id_ed25519$", re.IGNORECASE),
    re.compile(r"(^|/)\.secrets(/|$)", re.IGNORECASE),
    re.compile(r"letsencrypt", re.IGNORECASE),
)

BEARER_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
LONG_HEX_PATTERN = re.compile(r"\b[A-Fa-f0-9]{32,}\b")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def _redact_path_string(value: str) -> str:
    for pattern in SENSITIVE_PATH_PATTERNS:
        if pattern.search(value):
            return REDACTED_PLACEHOLDER
    return value


def _scrub_string(value: str) -> str:
    scrubbed = BEARER_TOKEN_PATTERN.sub(r"\1" + REDACTED_PLACEHOLDER, value)
    scrubbed = LONG_HEX_PATTERN.sub(REDACTED_PLACEHOLDER, scrubbed)
    return scrubbed


def redact_target_paths(paths: list[Any]) -> list[Any]:
    return [
        _redact_path_string(item) if isinstance(item, str) else item for item in paths
    ]


def redact_payload(value: Any) -> Any:
    """Recursively redact a JSON-compatible payload in place by returning a copy."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                result[key] = REDACTED_PLACEHOLDER
                continue
            if key == "target_paths" and isinstance(child, list):
                result[key] = redact_target_paths(child)
                continue
            result[key] = redact_payload(child)
        return result
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value
