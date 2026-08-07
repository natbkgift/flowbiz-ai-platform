"""Validated configuration and result models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
UNIT_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}\.service$")
PLACEHOLDER_PATTERN = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
SENSITIVE_PARAMETER_NAME_PATTERN = re.compile(
    r"(?i)(?:authorization|credential|password|private[_-]?key|secret|token|api[_-]?key)"
)
FORBIDDEN_EXECUTABLE_NAMES = {
    "ash",
    "bash",
    "cmd",
    "dash",
    "fish",
    "ksh",
    "powershell",
    "pwsh",
    "sh",
    "zsh",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParameterRule(StrictModel):
    """Validation rule for one operation parameter."""

    description: str = Field(min_length=1, max_length=200)
    pattern: str = Field(min_length=1, max_length=500)
    min_length: int = Field(default=1, ge=0, le=512)
    max_length: int = Field(default=128, ge=1, le=2048)

    @field_validator("pattern")
    @classmethod
    def compile_pattern(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        return value

    @model_validator(mode="after")
    def validate_lengths(self) -> ParameterRule:
        if self.min_length > self.max_length:
            raise ValueError("min_length cannot exceed max_length")
        return self

    def validate_value(self, name: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Parameter {name!r} must be a string")
        if "\x00" in value:
            raise ValueError(f"Parameter {name!r} contains a NUL byte")
        if value.startswith("-"):
            raise ValueError(f"Parameter {name!r} cannot begin with a hyphen")
        if not self.min_length <= len(value) <= self.max_length:
            raise ValueError(
                f"Parameter {name!r} length must be between "
                f"{self.min_length} and {self.max_length}"
            )
        if re.fullmatch(self.pattern, value) is None:
            raise ValueError(f"Parameter {name!r} does not match its allowlist pattern")
        return value


class ActionConfig(StrictModel):
    """One fixed, server-side mutation action."""

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    argv: list[str] = Field(min_length=1, max_length=64)
    parameters: dict[str, ParameterRule] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    approval: Literal["host-confirmation", "operator-code"] = "operator-code"
    risk: Literal["moderate", "high", "critical"] = "high"
    enabled: bool = False
    working_directory: Path | None = None

    @model_validator(mode="after")
    def validate_argv_template(self) -> ActionConfig:
        if self.risk in {"high", "critical"} and self.approval != "operator-code":
            raise ValueError("High and critical actions require operator-code approval")

        for parameter_name in self.parameters:
            if SENSITIVE_PARAMETER_NAME_PATTERN.search(parameter_name):
                raise ValueError(
                    f"Sensitive parameter names are forbidden in action argv: {parameter_name!r}"
                )

        placeholders: set[str] = set()
        for index, token in enumerate(self.argv):
            if not token or "\x00" in token or "\n" in token or "\r" in token:
                raise ValueError(f"argv[{index}] contains an unsafe value")
            match = PLACEHOLDER_PATTERN.fullmatch(token)
            if match:
                if index == 0:
                    raise ValueError("The executable cannot be a parameter placeholder")
                placeholders.add(match.group(1))
            elif "{" in token or "}" in token:
                raise ValueError(
                    "Placeholders must occupy a complete argv element, for example {release_ref}"
                )

        if placeholders != set(self.parameters):
            missing = sorted(placeholders - set(self.parameters))
            unused = sorted(set(self.parameters) - placeholders)
            raise ValueError(
                "Action parameter/template mismatch; "
                f"missing_rules={missing}, unused_rules={unused}"
            )
        return self


class TargetConfig(StrictModel):
    """A bounded project or service target."""

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    systemd_unit: str | None = None
    project_path: Path | None = None
    health_url: str | None = None
    allow_logs: bool = False
    actions: dict[str, ActionConfig] = Field(default_factory=dict)

    @field_validator("systemd_unit")
    @classmethod
    def validate_systemd_unit(cls, value: str | None) -> str | None:
        if value is not None and UNIT_PATTERN.fullmatch(value) is None:
            raise ValueError("systemd_unit must be an explicit .service unit name")
        return value

    @field_validator("health_url")
    @classmethod
    def validate_health_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("health_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("health_url cannot contain credentials or fragments")
        return value

    @field_validator("actions")
    @classmethod
    def validate_action_ids(cls, value: dict[str, ActionConfig]) -> dict[str, ActionConfig]:
        for action_id in value:
            if SAFE_ID_PATTERN.fullmatch(action_id) is None:
                raise ValueError(f"Invalid action id: {action_id!r}")
        return value


class GatewaySettings(StrictModel):
    """Global safety policy."""

    mutation_mode: Literal["disabled", "plan-only", "enabled"] = "disabled"
    state_dir: Path = Path("/var/lib/flowbiz-vps-mcp")
    executor_socket: Path = Path("/run/flowbiz-vps-mcp/executor.sock")
    executor_state_dir: Path = Path("/var/lib/flowbiz-vps-mcp-executor")
    allowed_path_roots: list[Path] = Field(
        default_factory=lambda: [Path("/opt/flowbiz"), Path("/srv/flowbiz")]
    )
    allowed_executables: list[Path] = Field(
        default_factory=lambda: [
            Path("/usr/bin/git"),
            Path("/usr/bin/journalctl"),
            Path("/usr/bin/systemctl"),
        ]
    )
    allowed_health_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "::1"]
    )
    read_timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_output_bytes: int = Field(default=65536, ge=1024, le=1048576)
    max_log_lines: int = Field(default=300, ge=10, le=2000)
    operation_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    operator_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    reason_min_length: int = Field(default=12, ge=4, le=100)
    redact_patterns: list[str] = Field(
        default_factory=lambda: [
            r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s]+",
            (
                r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)"
                r"\s*[:=]\s*)[^\s,;]+"
            ),
            r"\bsk-[A-Za-z0-9_-]{12,}\b",
            r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
        ]
    )

    @field_validator(
        "state_dir",
        "executor_socket",
        "executor_state_dir",
        mode="after",
    )
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Path must be absolute")
        return value

    @field_validator("allowed_path_roots", "allowed_executables", mode="after")
    @classmethod
    def require_absolute_paths(cls, values: list[Path]) -> list[Path]:
        if not values:
            raise ValueError("At least one path is required")
        for value in values:
            if not value.is_absolute():
                raise ValueError(f"Path must be absolute: {value}")
        return values

    @field_validator("redact_patterns")
    @classmethod
    def validate_redact_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"Invalid redaction pattern: {exc}") from exc
        return values


class GatewayConfig(StrictModel):
    """Complete gateway configuration."""

    version: Literal[1] = 1
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    targets: dict[str, TargetConfig]

    @field_validator("targets")
    @classmethod
    def validate_target_ids(cls, value: dict[str, TargetConfig]) -> dict[str, TargetConfig]:
        if not value:
            raise ValueError("At least one target is required")
        for target_id in value:
            if SAFE_ID_PATTERN.fullmatch(target_id) is None:
                raise ValueError(f"Invalid target id: {target_id!r}")
        return value

    @model_validator(mode="after")
    def validate_cross_references(self) -> GatewayConfig:
        allowed_executables = {str(path) for path in self.gateway.allowed_executables}
        allowed_health_hosts = {host.lower() for host in self.gateway.allowed_health_hosts}

        for target_id, target in self.targets.items():
            if target.project_path is not None:
                _require_within_roots(
                    target.project_path,
                    self.gateway.allowed_path_roots,
                    f"target {target_id!r} project_path",
                )
            if target.health_url is not None:
                host = (urlparse(target.health_url).hostname or "").lower()
                if host not in allowed_health_hosts:
                    raise ValueError(
                        f"target {target_id!r} health host {host!r} is not allowlisted"
                    )

            for action_id, action in target.actions.items():
                executable = Path(action.argv[0])
                if not executable.is_absolute():
                    raise ValueError(
                        f"target {target_id!r} action {action_id!r} executable must be absolute"
                    )
                if executable.name.lower() in FORBIDDEN_EXECUTABLE_NAMES:
                    raise ValueError(
                        f"target {target_id!r} action {action_id!r} cannot invoke a shell"
                    )
                if str(executable) not in allowed_executables:
                    raise ValueError(
                        f"target {target_id!r} action {action_id!r} executable "
                        f"{str(executable)!r} is not allowlisted"
                    )
                if action.working_directory is not None:
                    _require_within_roots(
                        action.working_directory,
                        self.gateway.allowed_path_roots,
                        f"target {target_id!r} action {action_id!r} working_directory",
                    )
        return self


def _require_within_roots(path: Path, roots: list[Path], label: str) -> None:
    candidate = path.resolve(strict=False)
    for root in roots:
        resolved_root = root.resolve(strict=False)
        if candidate == resolved_root or resolved_root in candidate.parents:
            return
    raise ValueError(f"{label} must be inside an allowed_path_root")
