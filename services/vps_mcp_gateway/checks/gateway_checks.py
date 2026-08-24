from pathlib import Path

from flowbiz_vps_mcp.config import config_fingerprint
from flowbiz_vps_mcp.gateway import FlowBizVpsGateway
from flowbiz_vps_mcp.models import GatewayConfig
from flowbiz_vps_mcp.security import confirmation_phrase
from flowbiz_vps_mcp.store import SQLiteStore


def make_config(tmp_path: Path, approval: str = "host-confirmation") -> GatewayConfig:
    root = tmp_path / "flowbiz"
    root.mkdir()
    raw = {
        "version": 1,
        "gateway": {
            "mutation_mode": "enabled",
            "state_dir": str(tmp_path / "gateway-state"),
            "executor_socket": str(tmp_path / "executor.sock"),
            "executor_state_dir": str(tmp_path / "executor-state"),
            "allowed_path_roots": [str(root)],
            "allowed_executables": ["/bin/echo"],
            "allowed_health_hosts": ["127.0.0.1"],
            "operation_ttl_seconds": 600,
            "operator_code_ttl_seconds": 300,
        },
        "targets": {
            "demo": {
                "title": "Demo",
                "description": "Test target",
                "project_path": str(root),
                "actions": {
                    "echo_release": {
                        "title": "Echo release",
                        "description": "Test execution",
                        "argv": ["/bin/echo", "{release_ref}"],
                        "parameters": {
                            "release_ref": {
                                "description": "Exact SHA",
                                "pattern": "^[0-9a-f]{40}$",
                                "min_length": 40,
                                "max_length": 40,
                            }
                        },
                        "approval": approval,
                        "risk": "moderate" if approval == "host-confirmation" else "high",
                        "enabled": True,
                    }
                },
            }
        },
    }
    return GatewayConfig.model_validate(raw)


def test_plan_is_immutable_and_idempotent(tmp_path: Path) -> None:
    gateway = FlowBizVpsGateway(make_config(tmp_path))
    first = gateway.plan_operation(
        target_id="demo",
        action_id="echo_release",
        parameters={"release_ref": "a" * 40},
        reason="Verify exact release deployment",
        idempotency_key="release-demo-001",
        actor="test",
    )
    second = gateway.plan_operation(
        target_id="demo",
        action_id="echo_release",
        parameters={"release_ref": "a" * 40},
        reason="Verify exact release deployment",
        idempotency_key="release-demo-001",
        actor="test",
    )
    assert first["operation_id"] == second["operation_id"]
    assert first["digest"] == second["digest"]
    assert first["required_confirmation"] == confirmation_phrase(
        first["operation_id"], first["digest"]
    )


def test_operator_code_is_one_time(tmp_path: Path) -> None:
    config = make_config(tmp_path, approval="operator-code")
    gateway = FlowBizVpsGateway(config)
    plan = gateway.plan_operation(
        target_id="demo",
        action_id="echo_release",
        parameters={"release_ref": "b" * 40},
        reason="Deploy an independently verified release",
        idempotency_key=None,
        actor="test",
    )
    store = SQLiteStore(config.gateway.executor_state_dir / "executor.sqlite3")
    code, _ = store.issue_operator_code(plan["operation_id"], plan["digest"], 300)
    store.consume_operator_code(plan["operation_id"], plan["digest"], code)
    try:
        store.consume_operator_code(plan["operation_id"], plan["digest"], code)
    except ValueError as exc:
        assert "already been consumed" in str(exc)
    else:
        raise AssertionError("operator code replay was not rejected")


def test_operator_code_cannot_be_reissued(tmp_path: Path) -> None:
    config = make_config(tmp_path, approval="operator-code")
    gateway = FlowBizVpsGateway(config)
    plan = gateway.plan_operation(
        target_id="demo",
        action_id="echo_release",
        parameters={"release_ref": "e" * 40},
        reason="Issue exactly one independent operator approval",
        idempotency_key=None,
        actor="test",
    )
    store = SQLiteStore(config.gateway.executor_state_dir / "executor.sqlite3")
    store.issue_operator_code(plan["operation_id"], plan["digest"], 300)
    try:
        store.issue_operator_code(plan["operation_id"], plan["digest"], 300)
    except ValueError as exc:
        assert "already issued" in str(exc)
        assert "new operation plan" in str(exc)
    else:
        raise AssertionError("operator code reissuance was not rejected")


def test_config_fingerprint_is_stable(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert config_fingerprint(config) == config_fingerprint(config)


def test_end_to_end_gateway_to_privileged_executor(tmp_path: Path) -> None:
    import threading

    import yaml

    from flowbiz_vps_mcp.executor_daemon import ExecutorServer, ExecutorService

    config = make_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    server = ExecutorServer(config.gateway.executor_socket, ExecutorService(config_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        gateway = FlowBizVpsGateway(config)
        plan = gateway.plan_operation(
            target_id="demo",
            action_id="echo_release",
            parameters={"release_ref": "c" * 40},
            reason="Execute a bounded end-to-end test",
            idempotency_key=None,
            actor="test",
        )
        result = gateway.execute_operation(
            operation_id=plan["operation_id"],
            confirmation=plan["required_confirmation"],
            operator_code=None,
            actor="test",
        )
        assert result["status"] == "succeeded"
        assert result["exit_code"] == 0
        assert "c" * 40 in result["stdout"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_failed_command_preserves_real_exit_and_output(tmp_path: Path) -> None:
    import threading

    import yaml

    from flowbiz_vps_mcp.executor_daemon import ExecutorServer, ExecutorService

    config = make_config(tmp_path)
    action = config.targets["demo"].actions["echo_release"]
    action.argv = ["/usr/bin/false", "{release_ref}"]
    config.gateway.allowed_executables.append(Path("/usr/bin/false"))
    # Revalidate after the test-only mutation so cross-references remain enforced.
    config = GatewayConfig.model_validate(config.model_dump(mode="json"))
    config_path = tmp_path / "config-failure.yaml"
    config_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    server = ExecutorServer(config.gateway.executor_socket, ExecutorService(config_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        gateway = FlowBizVpsGateway(config)
        plan = gateway.plan_operation(
            target_id="demo",
            action_id="echo_release",
            parameters={"release_ref": "d" * 40},
            reason="Verify failed commands retain exact evidence",
            idempotency_key=None,
            actor="test",
        )
        result = gateway.execute_operation(
            operation_id=plan["operation_id"],
            confirmation=plan["required_confirmation"],
            operator_code=None,
            actor="test",
        )
        assert result["status"] == "failed"
        assert result["exit_code"] == 1
        assert result["error"] is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
