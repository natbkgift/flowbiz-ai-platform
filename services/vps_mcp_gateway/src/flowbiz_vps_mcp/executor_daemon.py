"""Privileged local executor. It accepts only configured actions over a Unix socket."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socketserver
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from .config import config_fingerprint, load_config, resolve_config_path
from .executor_protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, PROTOCOL_VERSION
from .runner import CommandRunner
from .security import (
    Redactor,
    ensure_private_root_directory,
    ensure_secure_root_config,
    ensure_trusted_root_executable,
    operation_digest,
    render_action_argv,
    verify_confirmation,
)
from .store import SQLiteStore

LOGGER = logging.getLogger("flowbiz_vps_mcp.executor")


class ExecutorService:
    def __init__(self, config_path: Path, *, enforce_secure_config: bool = False) -> None:
        self.config_path = config_path
        self.enforce_secure_config = enforce_secure_config

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.enforce_secure_config:
            ensure_secure_root_config(self.config_path)
        config = load_config(self.config_path)
        settings = config.gateway
        if self.enforce_secure_config:
            ensure_private_root_directory(settings.executor_state_dir)
        if settings.mutation_mode != "enabled":
            raise ValueError("Privileged execution is disabled by mutation_mode")

        required_string_fields = [
            "operation_id",
            "target",
            "action",
            "reason",
            "digest",
            "config_fingerprint",
        ]
        for field in required_string_fields:
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise ValueError(f"Missing or invalid field: {field}")

        operation_id = payload["operation_id"]
        target_id = payload["target"]
        action_id = payload["action"]
        reason = payload["reason"]
        supplied_digest = payload["digest"]
        supplied_fingerprint = payload["config_fingerprint"]
        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in parameters.items()
        ):
            raise ValueError("parameters must be an object of string values")

        current_fingerprint = config_fingerprint(config)
        if supplied_fingerprint != current_fingerprint:
            raise ValueError("Configuration changed after planning; create a new operation plan")

        target = config.targets.get(target_id)
        if target is None:
            raise ValueError("Target is not allowlisted")
        action = target.actions.get(action_id)
        if action is None or not action.enabled:
            raise ValueError("Action is not allowlisted or is disabled")

        argv, validated_parameters = render_action_argv(
            action.argv, action.parameters, parameters
        )
        expected_digest = operation_digest(
            operation_id=operation_id,
            target=target_id,
            action=action_id,
            parameters=validated_parameters,
            reason=reason,
            argv=argv,
            config_fingerprint=current_fingerprint,
        )
        if supplied_digest != expected_digest:
            raise ValueError("Operation digest does not match the current allowlisted command")

        ensure_trusted_root_executable(Path(argv[0]))

        store = SQLiteStore(settings.executor_state_dir / "executor.sqlite3")
        existing = store.begin_executor_record(
            operation_id=operation_id,
            digest=expected_digest,
            target=target_id,
            action=action_id,
        )
        if existing is not None:
            return {"ok": True, "replayed": True, "record": existing}

        try:
            if action.approval == "host-confirmation":
                confirmation = payload.get("confirmation")
                if not isinstance(confirmation, str) or not verify_confirmation(
                    operation_id, expected_digest, confirmation
                ):
                    raise ValueError("Exact host confirmation phrase is required")
            else:
                operator_code = payload.get("operator_code")
                if not isinstance(operator_code, str) or not operator_code:
                    raise ValueError("One-time operator approval code is required")
                store.consume_operator_code(operation_id, expected_digest, operator_code)

            runner = CommandRunner(
                max_output_bytes=settings.max_output_bytes,
                redactor=Redactor(settings.redact_patterns),
            )
            result = runner.run(
                argv,
                timeout_seconds=action.timeout_seconds,
                working_directory=action.working_directory,
            )
            result_payload = {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            }
            status = "succeeded" if result.exit_code == 0 and not result.timed_out else "failed"
            record = store.complete_executor_record(
                operation_id,
                status=status,
                exit_code=result.exit_code,
                result=result_payload,
            )
            return {"ok": status == "succeeded", "replayed": False, "record": record}
        except Exception as exc:
            failure_payload = {"error": Redactor(settings.redact_patterns).redact(str(exc))}
            try:
                store.complete_executor_record(
                    operation_id,
                    status="failed",
                    exit_code=125,
                    result=failure_payload,
                )
            except Exception:
                LOGGER.exception("Failed to persist executor failure")
            raise


class ExecutorRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            self._write({"ok": False, "error": "Request too large"})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object")
            if payload.pop("version", None) != PROTOCOL_VERSION:
                raise ValueError("Unsupported executor protocol version")
            response = self.server.service.execute(payload)  # type: ignore[attr-defined]
        except Exception as exc:
            LOGGER.warning("Executor request denied: %s", exc)
            response = {"ok": False, "error": str(exc)}
        self._write(response)

    def _write(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = (
                json.dumps(
                    {"ok": False, "error": "Executor response exceeded the protocol limit"},
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        self.wfile.write(encoded)


class ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class ExecutorServer(ThreadingUnixServer):
    def __init__(self, socket_path: Path, service: ExecutorService) -> None:
        self.service = service
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        with suppress(FileNotFoundError):
            socket_path.unlink()
        super().__init__(str(socket_path), ExecutorRequestHandler)
        os.chmod(socket_path, 0o660)
        self.socket_path = socket_path

    def server_close(self) -> None:
        super().server_close()
        with suppress(FileNotFoundError):
            self.socket_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the privileged FlowBiz VPS MCP executor")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if os.geteuid() != 0:
        raise SystemExit("The privileged executor must run as root")
    os.umask(0o077)

    config_path = resolve_config_path(args.config)
    ensure_secure_root_config(config_path)
    config = load_config(config_path)
    ensure_private_root_directory(config.gateway.executor_state_dir)
    service = ExecutorService(config_path, enforce_secure_config=True)
    server = ExecutorServer(config.gateway.executor_socket, service)

    def stop(_signum: int, _frame: object) -> None:
        # socketserver.shutdown() must be called from a different thread than
        # serve_forever(), otherwise signal handling can deadlock.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOGGER.info("Executor listening on %s", config.gateway.executor_socket)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
