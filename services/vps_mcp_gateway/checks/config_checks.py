from pathlib import Path

import pytest

from flowbiz_vps_mcp.models import GatewayConfig


def base_config(tmp_path: Path) -> dict:
    root = tmp_path / "flowbiz"
    root.mkdir()
    executable = Path("/bin/echo")
    return {
        "version": 1,
        "gateway": {
            "mutation_mode": "enabled",
            "state_dir": str(tmp_path / "gateway-state"),
            "executor_socket": str(tmp_path / "executor.sock"),
            "executor_state_dir": str(tmp_path / "executor-state"),
            "allowed_path_roots": [str(root)],
            "allowed_executables": [str(executable)],
            "allowed_health_hosts": ["127.0.0.1"],
        },
        "targets": {
            "demo": {
                "title": "Demo",
                "description": "Test target",
                "project_path": str(root),
                "health_url": "http://127.0.0.1:9999/healthz",
                "actions": {
                    "echo_release": {
                        "title": "Echo",
                        "description": "Echo exact release",
                        "argv": [str(executable), "{release_ref}"],
                        "parameters": {
                            "release_ref": {
                                "description": "SHA",
                                "pattern": "^[0-9a-f]{40}$",
                                "min_length": 40,
                                "max_length": 40,
                            }
                        },
                        "approval": "host-confirmation",
                        "risk": "moderate",
                        "enabled": True,
                    }
                },
            }
        },
    }


def test_valid_config(tmp_path: Path) -> None:
    config = GatewayConfig.model_validate(base_config(tmp_path))
    assert config.targets["demo"].actions["echo_release"].enabled is True


def test_rejects_shell_executable(tmp_path: Path) -> None:
    raw = base_config(tmp_path)
    raw["gateway"]["allowed_executables"] = ["/bin/sh"]
    raw["targets"]["demo"]["actions"]["echo_release"]["argv"][0] = "/bin/sh"
    with pytest.raises(ValueError, match="cannot invoke a shell"):
        GatewayConfig.model_validate(raw)


def test_rejects_partial_placeholder(tmp_path: Path) -> None:
    raw = base_config(tmp_path)
    raw["targets"]["demo"]["actions"]["echo_release"]["argv"][1] = "release={release_ref}"
    with pytest.raises(ValueError, match="complete argv element"):
        GatewayConfig.model_validate(raw)


def test_rejects_health_ssrf_host(tmp_path: Path) -> None:
    raw = base_config(tmp_path)
    raw["targets"]["demo"]["health_url"] = "http://169.254.169.254/latest/meta-data"
    with pytest.raises(ValueError, match="not allowlisted"):
        GatewayConfig.model_validate(raw)


def test_high_risk_requires_operator_code(tmp_path: Path) -> None:
    raw = base_config(tmp_path)
    action = raw["targets"]["demo"]["actions"]["echo_release"]
    action["risk"] = "high"
    action["approval"] = "host-confirmation"
    with pytest.raises(ValueError, match="require operator-code"):
        GatewayConfig.model_validate(raw)


def test_rejects_sensitive_action_parameter_name(tmp_path: Path) -> None:
    raw = base_config(tmp_path)
    action = raw["targets"]["demo"]["actions"]["echo_release"]
    action["argv"] = ["/bin/echo", "{api_token}"]
    action["parameters"] = {
        "api_token": {
            "description": "Never permit secrets in command parameters",
            "pattern": "^[A-Za-z0-9]+$",
        }
    }
    with pytest.raises(ValueError, match="Sensitive parameter names"):
        GatewayConfig.model_validate(raw)


def test_example_config_uses_exact_bounded_argv() -> None:
    from flowbiz_vps_mcp.config import load_config

    example = Path(__file__).resolve().parents[1] / "config" / "targets.example.yaml"
    config = load_config(example)
    restart = config.targets["platform"].actions["restart"]
    deploy = config.targets["platform"].actions["deploy_release"]

    assert restart.argv == [
        "/usr/bin/systemctl",
        "restart",
        "flowbiz-ai-platform.service",
    ]
    assert deploy.argv == [
        "/opt/flowbiz/bin/deploy-platform-release",
        "{release_ref}",
    ]
    assert restart.enabled is False
    assert deploy.enabled is False
    assert config.gateway.mutation_mode == "plan-only"
