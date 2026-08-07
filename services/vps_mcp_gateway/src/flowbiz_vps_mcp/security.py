"""Security helpers shared by gateway and privileged executor."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONFIRMATION_PREFIX = "APPROVE-FLOWBIZ-OPERATION"
OPERATOR_APPROVAL_PREFIX = "ISSUE-FLOWBIZ-OPERATOR-CODE"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def operation_digest(
    *,
    operation_id: str,
    target: str,
    action: str,
    parameters: Mapping[str, str],
    reason: str,
    argv: list[str],
    config_fingerprint: str,
) -> str:
    payload = {
        "operation_id": operation_id,
        "target": target,
        "action": action,
        "parameters": dict(parameters),
        "reason": reason,
        "argv": argv,
        "config_fingerprint": config_fingerprint,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def confirmation_phrase(operation_id: str, digest: str) -> str:
    return f"{CONFIRMATION_PREFIX} {operation_id} {digest[:16]}"


def verify_confirmation(operation_id: str, digest: str, supplied: str) -> bool:
    return hmac.compare_digest(confirmation_phrase(operation_id, digest), supplied.strip())


def operator_approval_phrase(operation_id: str, digest: str) -> str:
    return f"{OPERATOR_APPROVAL_PREFIX} {operation_id} {digest[:16]}"


def verify_operator_approval(operation_id: str, digest: str, supplied: str) -> bool:
    return hmac.compare_digest(
        operator_approval_phrase(operation_id, digest),
        supplied.strip(),
    )


def make_operator_code() -> str:
    return secrets.token_urlsafe(18)


def operator_code_hash(operation_id: str, digest: str, code: str) -> str:
    payload = f"{operation_id}\x00{digest}\x00{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_operator_code(
    operation_id: str,
    digest: str,
    supplied: str,
    expected_hash: str,
) -> bool:
    actual = operator_code_hash(operation_id, digest, supplied)
    return hmac.compare_digest(actual, expected_hash)


class Redactor:
    """Best-effort output redaction. Secrets must still never be logged intentionally."""

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(pattern) for pattern in patterns]

    def redact(self, text: str) -> str:
        cleaned = text.replace("\x00", "�")
        for pattern in self._patterns:
            cleaned = pattern.sub(_redacted_replacement, cleaned)
        return cleaned


def _redacted_replacement(match: re.Match[str]) -> str:
    prefix = match.group(1) if match.lastindex else ""
    return f"{prefix}[REDACTED]"


def render_action_argv(
    argv_template: list[str],
    parameter_rules: Mapping[str, Any],
    supplied_parameters: Mapping[str, str] | None,
) -> tuple[list[str], dict[str, str]]:
    supplied = dict(supplied_parameters or {})
    expected = set(parameter_rules)
    actual = set(supplied)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"Operation parameters mismatch; missing={missing}, extra={extra}")

    validated: dict[str, str] = {}
    for name, rule in parameter_rules.items():
        validated[name] = rule.validate_value(name, supplied[name])

    rendered: list[str] = []
    for token in argv_template:
        if token.startswith("{") and token.endswith("}"):
            rendered.append(validated[token[1:-1]])
        else:
            rendered.append(token)
    return rendered, validated


def ensure_secure_root_config(path: str | Path) -> None:
    """Require an immutable-by-non-root, regular configuration file."""

    candidate = Path(path)
    components = _inspect_absolute_path(candidate)
    if len(components) < 2:
        raise ValueError("Root configuration path must name a file")

    for parent, parent_stat in components[:-1]:
        _require_root_controlled_directory(parent, parent_stat)

    file_path, file_stat = components[-1]
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("Root configuration must be a regular file")
    if file_stat.st_uid != 0:
        raise ValueError("Root configuration must be owned by root")
    if file_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError("Root configuration cannot be group- or world-writable")
    if file_path != candidate:
        raise ValueError("Root configuration path changed during inspection")


def ensure_private_root_directory(path: str | Path) -> None:
    """Require a root-owned directory inaccessible to group and other users."""

    candidate = Path(path)
    components = _inspect_absolute_path(candidate)
    if not components:
        raise ValueError("Private root directory path is invalid")

    for parent, parent_stat in components[:-1]:
        _require_root_controlled_directory(parent, parent_stat)

    directory, directory_stat = components[-1]
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError("Private root state path must be a directory")
    if directory_stat.st_uid != 0:
        raise ValueError("Private root state directory must be owned by root")
    if stat.S_IMODE(directory_stat.st_mode) & 0o077:
        raise ValueError("Private root state directory must not grant group/other access")
    if directory != candidate:
        raise ValueError("Private root state path changed during inspection")


def ensure_trusted_root_executable(executable: Any) -> None:
    """Reject mutable or non-root-owned executables before a privileged exec."""

    path = Path(executable)
    if not path.is_absolute():
        raise ValueError("Privileged executable path must be absolute")
    if path.is_symlink():
        raise ValueError("Privileged executable cannot be a symbolic link")
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise ValueError(f"Privileged executable cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("Privileged executable must be a regular file")
    if file_stat.st_uid != 0:
        raise ValueError("Privileged executable must be owned by root")
    if file_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError("Privileged executable cannot be group- or world-writable")
    if not file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        raise ValueError("Privileged executable is not executable")

    resolved = path.resolve(strict=True)
    for parent in resolved.parents:
        parent_stat = parent.stat()
        _require_root_controlled_directory(parent, parent_stat)
        if parent == Path("/"):
            break


def _inspect_absolute_path(path: Path) -> list[tuple[Path, Any]]:
    if not path.is_absolute():
        raise ValueError("Security-sensitive path must be absolute")

    current = Path(path.anchor)
    try:
        root_stat = current.lstat()
    except OSError as exc:
        raise ValueError(f"Security-sensitive path cannot be inspected: {exc}") from exc
    inspected: list[tuple[Path, Any]] = [(current, root_stat)]
    for part in path.parts[1:]:
        if part in {".", ".."}:
            raise ValueError("Security-sensitive path cannot contain traversal components")
        current /= part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise ValueError(f"Security-sensitive path cannot be inspected: {exc}") from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise ValueError(f"Security-sensitive path cannot contain symlinks: {current}")
        inspected.append((current, current_stat))
    return inspected


def _require_root_controlled_directory(path: Path, path_stat: Any) -> None:
    if not stat.S_ISDIR(path_stat.st_mode):
        raise ValueError(f"Security-sensitive parent is not a directory: {path}")
    if path_stat.st_uid != 0:
        raise ValueError(f"Security-sensitive parent is not root-owned: {path}")
    if path_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError(f"Security-sensitive parent is writable by non-root: {path}")
