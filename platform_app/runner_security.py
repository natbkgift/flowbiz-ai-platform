"""Transport authentication helpers for the internal runner boundary."""

from __future__ import annotations

import hashlib
import hmac
import time


class RunnerSignatureError(ValueError):
    """Raised when a runner callback signature is absent, stale, or invalid."""


def sign_callback(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return "v1=" + hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_callback_signature(
    *,
    secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    max_clock_skew_seconds: int,
    now: float | None = None,
) -> None:
    if not secret:
        raise RunnerSignatureError("callback verifier is not configured")
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise RunnerSignatureError("invalid callback timestamp") from exc
    if abs((now if now is not None else time.time()) - timestamp_value) > max_clock_skew_seconds:
        raise RunnerSignatureError("stale callback timestamp")
    expected = sign_callback(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise RunnerSignatureError("invalid callback signature")


def bearer_token(authorization: str | None) -> str:
    scheme, separator, value = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def token_matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(provided, expected)
