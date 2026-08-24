"""MCP tool surface. Never writes protocol logs to stdout."""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .config import load_config
from .gateway import FlowBizVpsGateway

logging.basicConfig(
    level=os.environ.get("FLOWBIZ_VPS_MCP_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

mcp = MCPServer(
    "FlowBiz VPS Operations",
    instructions=(
        "Internal FlowBiz VPS operations. Use read-only tools first. "
        "Never claim a mutation succeeded until execute_operation returns status=succeeded. "
        "Mutations are restricted to fixed server-side actions and may require explicit approval."
    ),
)

READ_ONLY = ToolAnnotations(
    title="Read-only VPS operation",
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
PLAN = ToolAnnotations(
    title="Plan bounded VPS operation",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
EXECUTE = ToolAnnotations(
    title="Execute approved VPS operation",
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)
CANCEL = ToolAnnotations(
    title="Cancel VPS operation plan",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


@lru_cache(maxsize=1)
def gateway() -> FlowBizVpsGateway:
    return FlowBizVpsGateway(load_config())


def actor() -> str:
    return os.environ.get("FLOWBIZ_VPS_MCP_ACTOR", "secure-mcp-tunnel")


@mcp.tool(title="Gateway information", annotations=READ_ONLY)
def gateway_info() -> dict[str, Any]:
    """Use this when checking gateway mode, safety controls, or executor availability."""
    return gateway().gateway_info()


@mcp.tool(title="List VPS targets", annotations=READ_ONLY)
def list_targets() -> dict[str, Any]:
    """Use this before other tools to discover allowlisted targets and actions."""
    return gateway().list_targets()


@mcp.tool(title="Server overview", annotations=READ_ONLY)
def server_overview() -> dict[str, Any]:
    """Use this to inspect bounded host capacity and uptime information."""
    return gateway().server_overview()


@mcp.tool(title="Service status", annotations=READ_ONLY)
def service_status(target: str) -> dict[str, Any]:
    """Use this to inspect the systemd state of one allowlisted target."""
    return gateway().service_status(target)


@mcp.tool(title="Service logs", annotations=READ_ONLY)
def service_logs(target: str, lines: int = 100, since_minutes: int = 60) -> dict[str, Any]:
    """Use this to read redacted recent journal logs for a target that permits log access."""
    return gateway().service_logs(target, lines=lines, since_minutes=since_minutes)


@mcp.tool(title="Project revision", annotations=READ_ONLY)
def project_revision(target: str) -> dict[str, Any]:
    """Use this to inspect exact Git HEAD, branch, and working-tree cleanliness."""
    return gateway().project_revision(target)


@mcp.tool(title="Health check", annotations=READ_ONLY)
def healthcheck(target: str) -> dict[str, Any]:
    """Use this to call the fixed health URL configured for one target."""
    return gateway().healthcheck(target)


@mcp.tool(title="Plan operation", annotations=PLAN)
def plan_operation(
    target: str,
    action: str,
    reason: str,
    parameters: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Use this to create an immutable, expiring plan for one fixed allowlisted action."""
    return gateway().plan_operation(
        target_id=target,
        action_id=action,
        parameters=parameters,
        reason=reason,
        idempotency_key=idempotency_key,
        actor=actor(),
    )


@mcp.tool(title="Execute operation", annotations=EXECUTE)
def execute_operation(
    operation_id: str,
    confirmation: str | None = None,
    operator_code: str | None = None,
) -> dict[str, Any]:
    """Use this only after reviewing a plan and receiving the required approval."""
    return gateway().execute_operation(
        operation_id=operation_id,
        confirmation=confirmation,
        operator_code=operator_code,
        actor=actor(),
    )


@mcp.tool(title="Cancel operation", annotations=CANCEL)
def cancel_operation(operation_id: str, reason: str) -> dict[str, Any]:
    """Use this to cancel an unexecuted operation plan."""
    return gateway().cancel_operation(operation_id, reason, actor())


@mcp.tool(title="Operation status", annotations=READ_ONLY)
def operation_status(operation_id: str) -> dict[str, Any]:
    """Use this to inspect the stored status and bounded output of an operation."""
    return gateway().get_operation(operation_id)


@mcp.tool(title="Recent audit events", annotations=READ_ONLY)
def recent_audit(limit: int = 50) -> dict[str, Any]:
    """Use this to inspect recent gateway decisions and execution outcomes."""
    return gateway().recent_audit(limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
