"""Unprivileged gateway operations exposed through MCP."""

from __future__ import annotations

import platform
import shutil
import urllib.error
import urllib.request
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import config_fingerprint
from .executor_protocol import send_executor_request
from .models import GatewayConfig
from .runner import CommandRunner
from .security import Redactor, confirmation_phrase, operation_digest, render_action_argv
from .store import SQLiteStore, iso, utc_now


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise urllib.error.HTTPError(req.full_url, code, "Redirects are disabled", headers, fp)


class FlowBizVpsGateway:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.fingerprint = config_fingerprint(config)
        settings = config.gateway
        self.store = SQLiteStore(settings.state_dir / "gateway.sqlite3")
        self.redactor = Redactor(settings.redact_patterns)
        self.runner = CommandRunner(
            max_output_bytes=settings.max_output_bytes,
            redactor=self.redactor,
        )

    def gateway_info(self) -> dict[str, Any]:
        return {
            "name": "FlowBiz VPS MCP Gateway",
            "version": "0.1.0",
            "transport": "stdio via OpenAI Secure MCP Tunnel",
            "mutation_mode": self.config.gateway.mutation_mode,
            "config_fingerprint": self.fingerprint,
            "executor_socket_configured": str(self.config.gateway.executor_socket),
            "executor_socket_available": self.config.gateway.executor_socket.exists(),
            "target_count": len(self.config.targets),
            "security": {
                "arbitrary_shell": False,
                "arbitrary_ssh": False,
                "fixed_action_allowlist": True,
                "root_executor_isolated": True,
                "audit_log": True,
                "high_risk_operator_code": True,
            },
        }

    def list_targets(self) -> dict[str, Any]:
        targets: list[dict[str, Any]] = []
        for target_id, target in sorted(self.config.targets.items()):
            targets.append(
                {
                    "target": target_id,
                    "title": target.title,
                    "description": target.description,
                    "capabilities": {
                        "service_status": target.systemd_unit is not None,
                        "service_logs": target.systemd_unit is not None and target.allow_logs,
                        "project_revision": target.project_path is not None,
                        "healthcheck": target.health_url is not None,
                    },
                    "actions": [
                        {
                            "action": action_id,
                            "title": action.title,
                            "description": action.description,
                            "enabled": action.enabled,
                            "risk": action.risk,
                            "approval": action.approval,
                            "parameters": {
                                name: rule.description for name, rule in action.parameters.items()
                            },
                        }
                        for action_id, action in sorted(target.actions.items())
                    ],
                }
            )
        return {"targets": targets, "mutation_mode": self.config.gateway.mutation_mode}

    def server_overview(self) -> dict[str, Any]:
        uptime_seconds = None
        load_average = None
        memory: dict[str, int] = {}
        with suppress(OSError, ValueError, IndexError):
            uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
        with suppress(OSError, ValueError):
            load_tokens = Path("/proc/loadavg").read_text().split()[:3]
            load_average = [float(token) for token in load_tokens]
        with suppress(OSError, ValueError, IndexError):
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                    memory[key] = int(value.strip().split()[0]) * 1024
        disk = shutil.disk_usage("/")
        return {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "kernel": platform.release(),
            "python": platform.python_version(),
            "uptime_seconds": uptime_seconds,
            "load_average_1_5_15": load_average,
            "memory_bytes": memory,
            "root_disk_bytes": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            },
        }

    def service_status(self, target_id: str) -> dict[str, Any]:
        target = self._target(target_id)
        if target.systemd_unit is None:
            raise ValueError("Target has no systemd_unit")
        result = self.runner.run(
            [
                "/usr/bin/systemctl",
                "show",
                target.systemd_unit,
                "--no-pager",
                (
                    "--property=Id,LoadState,ActiveState,SubState,UnitFileState,"
                    "MainPID,ExecMainStatus,ActiveEnterTimestamp"
                ),
            ],
            timeout_seconds=self.config.gateway.read_timeout_seconds,
        )
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value
        return {
            "target": target_id,
            "unit": target.systemd_unit,
            "exit_code": result.exit_code,
            "fields": fields,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
        }

    def service_logs(self, target_id: str, *, lines: int, since_minutes: int) -> dict[str, Any]:
        target = self._target(target_id)
        if target.systemd_unit is None or not target.allow_logs:
            raise ValueError("Logs are not enabled for this target")
        max_lines = self.config.gateway.max_log_lines
        if not 1 <= lines <= max_lines:
            raise ValueError(f"lines must be between 1 and {max_lines}")
        if not 1 <= since_minutes <= 10080:
            raise ValueError("since_minutes must be between 1 and 10080")
        result = self.runner.run(
            [
                "/usr/bin/journalctl",
                "--unit",
                target.systemd_unit,
                "--no-pager",
                "--output=short-iso",
                "--lines",
                str(lines),
                "--since",
                f"-{since_minutes} minutes",
            ],
            timeout_seconds=self.config.gateway.read_timeout_seconds,
        )
        return {
            "target": target_id,
            "unit": target.systemd_unit,
            "exit_code": result.exit_code,
            "logs": result.stdout,
            "stderr": result.stderr,
            "truncated": result.stdout_truncated,
            "duration_ms": result.duration_ms,
        }

    def project_revision(self, target_id: str) -> dict[str, Any]:
        target = self._target(target_id)
        if target.project_path is None:
            raise ValueError("Target has no project_path")
        path = target.project_path
        head = self.runner.run(
            ["/usr/bin/git", "-C", str(path), "rev-parse", "HEAD"],
            timeout_seconds=self.config.gateway.read_timeout_seconds,
        )
        branch = self.runner.run(
            ["/usr/bin/git", "-C", str(path), "branch", "--show-current"],
            timeout_seconds=self.config.gateway.read_timeout_seconds,
        )
        status = self.runner.run(
            ["/usr/bin/git", "-C", str(path), "status", "--short"],
            timeout_seconds=self.config.gateway.read_timeout_seconds,
        )
        return {
            "target": target_id,
            "project_path": str(path),
            "head": head.stdout.strip() if head.exit_code == 0 else None,
            "branch": branch.stdout.strip() if branch.exit_code == 0 else None,
            "clean": status.exit_code == 0 and not status.stdout.strip(),
            "status_short": status.stdout,
            "errors": [
                item.stderr
                for item in (head, branch, status)
                if item.exit_code != 0 and item.stderr
            ],
        }

    def healthcheck(self, target_id: str) -> dict[str, Any]:
        target = self._target(target_id)
        if target.health_url is None:
            raise ValueError("Target has no health_url")
        request = urllib.request.Request(
            target.health_url,
            method="GET",
            headers={"User-Agent": "flowbiz-vps-mcp/0.1"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
        started = utc_now()
        try:
            with opener.open(request, timeout=self.config.gateway.read_timeout_seconds) as response:
                body = response.read(self.config.gateway.max_output_bytes + 1)
                truncated = len(body) > self.config.gateway.max_output_bytes
                body = body[: self.config.gateway.max_output_bytes]
                return {
                    "target": target_id,
                    "url": target.health_url,
                    "ok": 200 <= response.status < 300,
                    "status_code": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "body": self.redactor.redact(body.decode("utf-8", errors="replace")),
                    "truncated": truncated,
                    "duration_ms": round((utc_now() - started).total_seconds() * 1000),
                }
        except urllib.error.HTTPError as exc:
            body = self.redactor.redact(
                exc.read(self.config.gateway.max_output_bytes).decode("utf-8", errors="replace")
            )
            return {
                "target": target_id,
                "url": target.health_url,
                "ok": False,
                "status_code": exc.code,
                "body": body,
                "error": str(exc),
                "duration_ms": round((utc_now() - started).total_seconds() * 1000),
            }
        except OSError as exc:
            return {
                "target": target_id,
                "url": target.health_url,
                "ok": False,
                "status_code": None,
                "error": str(exc),
                "duration_ms": round((utc_now() - started).total_seconds() * 1000),
            }

    def plan_operation(
        self,
        *,
        target_id: str,
        action_id: str,
        parameters: dict[str, str] | None,
        reason: str,
        idempotency_key: str | None,
        actor: str,
    ) -> dict[str, Any]:
        settings = self.config.gateway
        if settings.mutation_mode == "disabled":
            raise ValueError("Mutation planning is disabled")
        normalized_reason = reason.strip()
        if len(normalized_reason) < settings.reason_min_length:
            raise ValueError(
                "reason must contain at least "
                f"{settings.reason_min_length} non-whitespace characters"
            )
        if len(reason) > 1000:
            raise ValueError("reason is too long")
        if self.redactor.redact(normalized_reason) != normalized_reason:
            raise ValueError("reason appears to contain sensitive data")
        if idempotency_key is not None:
            if not 8 <= len(idempotency_key) <= 128:
                raise ValueError("idempotency_key must be 8-128 characters")
            if not all(character.isalnum() or character in "._:-" for character in idempotency_key):
                raise ValueError("idempotency_key contains unsupported characters")

        target = self._target(target_id)
        action = target.actions.get(action_id)
        if action is None or not action.enabled:
            raise ValueError("Action is not allowlisted or is disabled")
        argv, validated_parameters = render_action_argv(
            action.argv, action.parameters, parameters
        )
        if any(self.redactor.redact(value) != value for value in validated_parameters.values()):
            raise ValueError("operation parameter appears to contain sensitive data")
        operation_id = f"op_{uuid4().hex}"
        created_at = utc_now()
        digest = operation_digest(
            operation_id=operation_id,
            target=target_id,
            action=action_id,
            parameters=validated_parameters,
            reason=normalized_reason,
            argv=argv,
            config_fingerprint=self.fingerprint,
        )
        record = self.store.create_operation(
            {
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "target": target_id,
                "action": action_id,
                "parameters": validated_parameters,
                "reason": normalized_reason,
                "argv": argv,
                "config_fingerprint": self.fingerprint,
                "digest": digest,
                "approval_mode": action.approval,
                "created_at": iso(created_at),
                "expires_at": iso(created_at + timedelta(seconds=settings.operation_ttl_seconds)),
            }
        )
        self.store.add_audit(
            "operation_planned",
            actor=actor,
            operation_id=record["operation_id"],
            details={
                "target": record["target"],
                "action": record["action"],
                "digest": record["digest"],
                "approval_mode": record["approval_mode"],
            },
        )
        return self._public_operation(record, include_confirmation=True)

    def execute_operation(
        self,
        *,
        operation_id: str,
        confirmation: str | None,
        operator_code: str | None,
        actor: str,
    ) -> dict[str, Any]:
        settings = self.config.gateway
        if settings.mutation_mode != "enabled":
            raise ValueError("Mutation execution is not enabled")
        operation = self.store.get_operation(operation_id)
        if operation is None:
            raise ValueError("Unknown operation_id")
        if operation["status"] == "succeeded":
            return self._public_operation(operation, include_confirmation=False)
        if operation["config_fingerprint"] != self.fingerprint:
            raise ValueError("Configuration changed after planning; create a new operation plan")

        running = self.store.mark_operation_running(operation_id, operation["digest"])
        self.store.add_audit(
            "operation_execution_requested",
            actor=actor,
            operation_id=operation_id,
            details={"target": running["target"], "action": running["action"]},
        )
        try:
            response = send_executor_request(
                settings.executor_socket,
                {
                    "operation_id": running["operation_id"],
                    "target": running["target"],
                    "action": running["action"],
                    "parameters": running["parameters"],
                    "reason": running["reason"],
                    "digest": running["digest"],
                    "config_fingerprint": running["config_fingerprint"],
                    "confirmation": confirmation,
                    "operator_code": operator_code,
                },
                timeout=max(30, self._action_timeout(running) + 10),
            )
            executor_record = response.get("record")
            if not isinstance(executor_record, dict):
                error = self.redactor.redact(
                    str(response.get("error") or "Privileged executor rejected operation")
                )
                completed = self.store.complete_operation(
                    operation_id,
                    status="failed",
                    exit_code=125,
                    stdout="",
                    stderr="",
                    duration_ms=None,
                    error=error,
                )
                self.store.add_audit(
                    "operation_failed",
                    actor="executor",
                    operation_id=operation_id,
                    details={"error": error},
                )
                return self._public_operation(completed, include_confirmation=False)

            result = executor_record.get("result") or {}
            status = executor_record["status"]
            completed = self.store.complete_operation(
                operation_id,
                status=status,
                exit_code=result.get("exit_code"),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                duration_ms=result.get("duration_ms"),
                error=result.get("error"),
            )
            self.store.add_audit(
                "operation_completed",
                actor="executor",
                operation_id=operation_id,
                details={"status": status, "exit_code": completed["exit_code"]},
            )
            return self._public_operation(completed, include_confirmation=False)
        except Exception as exc:
            error = self.redactor.redact(str(exc))
            completed = self.store.complete_operation(
                operation_id,
                status="failed",
                exit_code=125,
                stdout="",
                stderr="",
                duration_ms=None,
                error=error,
            )
            self.store.add_audit(
                "operation_failed",
                actor="gateway",
                operation_id=operation_id,
                details={"error": error},
            )
            return self._public_operation(completed, include_confirmation=False)

    def cancel_operation(self, operation_id: str, reason: str, actor: str) -> dict[str, Any]:
        normalized_reason = reason.strip()
        if len(normalized_reason) < 4:
            raise ValueError("Cancellation reason is required")
        if len(normalized_reason) > 1000:
            raise ValueError("Cancellation reason is too long")
        if self.redactor.redact(normalized_reason) != normalized_reason:
            raise ValueError("cancellation reason appears to contain sensitive data")
        record = self.store.cancel_operation(operation_id, normalized_reason)
        self.store.add_audit(
            "operation_cancelled",
            actor=actor,
            operation_id=operation_id,
            details={"reason": normalized_reason},
        )
        return self._public_operation(record, include_confirmation=False)

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        record = self.store.get_operation(operation_id)
        if record is None:
            raise ValueError("Unknown operation_id")
        return self._public_operation(record, include_confirmation=False)

    def recent_audit(self, limit: int) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        return {"events": self.store.recent_audit(limit)}

    def _target(self, target_id: str) -> Any:
        target = self.config.targets.get(target_id)
        if target is None:
            raise ValueError("Target is not allowlisted")
        return target

    def _action_timeout(self, operation: dict[str, Any]) -> int:
        return self.config.targets[operation["target"]].actions[operation["action"]].timeout_seconds

    @staticmethod
    def _public_operation(record: dict[str, Any], *, include_confirmation: bool) -> dict[str, Any]:
        result = {
            key: value
            for key, value in record.items()
            if key not in {"argv", "config_fingerprint"}
        }
        result["command_preview"] = record["argv"]
        if include_confirmation:
            if record["approval_mode"] == "host-confirmation":
                result["required_confirmation"] = confirmation_phrase(
                    record["operation_id"], record["digest"]
                )
            else:
                result["required_confirmation"] = None
                result["operator_code_required"] = True
                result["operator_instruction"] = (
                    "A server operator must issue a one-time code with "
                    "flowbiz-vps-mcp-admin approve-operation before execution."
                )
        return result
