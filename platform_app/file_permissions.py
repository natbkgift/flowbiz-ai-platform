"""Read-only checks for sensitive platform file permissions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import stat


@dataclass(frozen=True)
class PermissionFinding:
    path: str
    kind: str
    status: str
    message: str
    mode: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _mode_text(path: Path) -> str:
    return oct(_mode(path))


def _restricted_0600(path: Path, kind: str) -> PermissionFinding:
    if os.name == "nt":
        return PermissionFinding(
            path=str(path),
            kind=kind,
            status="manual_review",
            mode=None,
            message="POSIX mode check is not available on Windows",
        )
    mode = _mode(path)
    if mode & 0o077:
        return PermissionFinding(
            path=str(path),
            kind=kind,
            status="bad",
            mode=oct(mode),
            message="file is readable or writable by group/other; expected 0o600",
        )
    return PermissionFinding(
        path=str(path),
        kind=kind,
        status="ok",
        mode=oct(mode),
        message="file permission is restricted",
    )


def scan_platform_file_permissions(root: Path) -> list[PermissionFinding]:
    """Scan sensitive file paths without opening or reading their contents."""

    root = root.expanduser().resolve()
    findings: list[PermissionFinding] = []

    env_path = root / ".env"
    if env_path.exists():
        findings.append(_restricted_0600(env_path, ".env"))
    else:
        findings.append(
            PermissionFinding(
                path=str(env_path),
                kind=".env",
                status="missing",
                mode=None,
                message=".env not present at this path",
            )
        )

    for path in sorted(root.glob(".env.backup*")):
        findings.append(
            PermissionFinding(
                path=str(path),
                kind=".env.backup",
                status="bad",
                mode=_mode_text(path) if os.name != "nt" else None,
                message="backup env files must not exist in the active repo path",
            )
        )

    for path in sorted((root / "platform_data").glob("*.db*")):
        if path.is_file():
            findings.append(_restricted_0600(path, "sqlite_db"))

    for path in sorted(root.glob("*bootstrap*api-key*.txt")):
        if path.is_file():
            findings.append(_restricted_0600(path, "bootstrap_admin_key"))

    return findings
