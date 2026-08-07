"""Local operator CLI. Approval-code issuance is intentionally not exposed through MCP."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import config_fingerprint, load_config, resolve_config_path
from .gateway import FlowBizVpsGateway
from .security import (
    ensure_private_root_directory,
    ensure_secure_root_config,
    operator_approval_phrase,
    verify_operator_approval,
)
from .store import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FlowBiz VPS MCP gateway administration")
    parser.add_argument("--config", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-config")
    subparsers.add_parser("gateway-info")

    show = subparsers.add_parser("show-operation")
    show.add_argument("operation_id")

    approve = subparsers.add_parser("approve-operation")
    approve.add_argument("operation_id")
    approve.add_argument("digest")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = resolve_config_path(args.config)

    if args.command == "approve-operation":
        if os.geteuid() != 0:
            raise SystemExit("approve-operation must be run as root on the VPS")
        if not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
            raise SystemExit("approve-operation requires an interactive local TTY")
        os.umask(0o077)
        ensure_secure_root_config(config_path)

    config = load_config(config_path)
    if args.command == "check-config":
        print(
            json.dumps(
                {
                    "ok": True,
                    "fingerprint": config_fingerprint(config),
                    "mutation_mode": config.gateway.mutation_mode,
                    "targets": sorted(config.targets),
                },
                indent=2,
            )
        )
        return

    if args.command == "gateway-info":
        print(json.dumps(FlowBizVpsGateway(config).gateway_info(), indent=2))
        return

    if args.command == "show-operation":
        record = FlowBizVpsGateway(config).get_operation(args.operation_id)
        print(json.dumps(record, indent=2))
        return

    if args.command == "approve-operation":
        gateway = FlowBizVpsGateway(config)
        operation = gateway.store.get_operation(args.operation_id)
        if operation is None:
            raise SystemExit("Unknown operation_id in the gateway plan store")
        if operation["digest"] != args.digest:
            raise SystemExit("Digest does not match the stored immutable operation plan")
        if operation["approval_mode"] != "operator-code":
            raise SystemExit("This operation does not use operator-code approval")
        if operation["status"] != "planned":
            raise SystemExit(f"Operation is not approvable from status {operation['status']!r}")
        if datetime.fromisoformat(operation["expires_at"]) <= datetime.now(UTC):
            raise SystemExit("Operation plan has expired")
        if operation["config_fingerprint"] != config_fingerprint(config):
            raise SystemExit("Configuration changed after planning; create a new operation plan")

        ensure_private_root_directory(config.gateway.executor_state_dir)
        required_phrase = operator_approval_phrase(args.operation_id, args.digest)
        print("Review the immutable operation before issuing a one-time code:")
        print(f"  operation_id: {operation['operation_id']}")
        print(f"  target/action: {operation['target']} / {operation['action']}")
        print(f"  reason: {operation['reason']}")
        print(f"  command: {shlex.join(operation['argv'])}")
        print(f"  digest: {operation['digest']}")
        print(f"  plan expires: {operation['expires_at']}")
        print("\nType this exact phrase to continue:")
        print(required_phrase)
        supplied = input("> ")
        if not verify_operator_approval(args.operation_id, args.digest, supplied):
            raise SystemExit("Exact operator approval phrase did not match; no code was issued")

        store = SQLiteStore(config.gateway.executor_state_dir / "executor.sqlite3")
        code, expires_at = store.issue_operator_code(
            args.operation_id,
            args.digest,
            config.gateway.operator_code_ttl_seconds,
        )
        print(
            json.dumps(
                {
                    "operation_id": args.operation_id,
                    "digest": args.digest,
                    "operator_code": code,
                    "expires_at": expires_at,
                    "warning": (
                        "The code is shown once and cannot be reissued for this operation. "
                        "Send it only to the approved execution call."
                    ),
                },
                indent=2,
            )
        )
        return

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    main()
