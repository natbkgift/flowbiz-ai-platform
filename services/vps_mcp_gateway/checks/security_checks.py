from flowbiz_vps_mcp.models import ParameterRule
from flowbiz_vps_mcp.runner import CommandRunner
from flowbiz_vps_mcp.security import (
    Redactor,
    confirmation_phrase,
    operator_approval_phrase,
    render_action_argv,
    verify_confirmation,
    verify_operator_approval,
)


def test_parameter_is_separate_argv_and_validated() -> None:
    rule = ParameterRule(
        description="sha",
        pattern="^[0-9a-f]{40}$",
        min_length=40,
        max_length=40,
    )
    sha = "a" * 40
    argv, values = render_action_argv(
        ["/bin/echo", "{release_ref}"],
        {"release_ref": rule},
        {"release_ref": sha},
    )
    assert argv == ["/bin/echo", sha]
    assert values == {"release_ref": sha}


def test_confirmation_is_exact() -> None:
    phrase = confirmation_phrase("op_1", "f" * 64)
    assert verify_confirmation("op_1", "f" * 64, phrase)
    assert not verify_confirmation("op_1", "f" * 64, phrase + " now")


def test_operator_approval_phrase_is_exact() -> None:
    phrase = operator_approval_phrase("op_2", "e" * 64)
    assert phrase == "ISSUE-FLOWBIZ-OPERATOR-CODE op_2 eeeeeeeeeeeeeeee"
    assert verify_operator_approval("op_2", "e" * 64, phrase)
    assert not verify_operator_approval("op_2", "e" * 64, phrase.lower())


def test_redactor_masks_common_secrets() -> None:
    redactor = Redactor(
        [r"(?i)((?:token|password)\s*[:=]\s*)[^\s]+", r"\bsk-[A-Za-z0-9_-]{12,}\b"]
    )
    text = redactor.redact("token=abc123 password: xyz sk-abcdefghijklmnop")
    assert "abc123" not in text
    assert "xyz" not in text
    assert "sk-abcdefghijklmnop" not in text
    assert text.count("[REDACTED]") == 3


def test_trusted_root_executable_accepts_system_binary() -> None:
    from flowbiz_vps_mcp.security import ensure_trusted_root_executable

    ensure_trusted_root_executable("/usr/bin/echo")


def test_command_runner_uses_restricted_path() -> None:
    runner = CommandRunner(max_output_bytes=4096, redactor=Redactor([]))
    result = runner.run(["/usr/bin/env"], timeout_seconds=5)
    assert result.exit_code == 0
    assert "PATH=/usr/sbin:/usr/bin:/sbin:/bin" in result.stdout
    assert "/usr/local/bin" not in result.stdout


def test_parameter_rejects_leading_hyphen() -> None:
    rule = ParameterRule(
        description="bounded identifier",
        pattern="^[A-Za-z0-9_-]+$",
        min_length=1,
        max_length=40,
    )
    try:
        rule.validate_value("release_ref", "--help")
    except ValueError as exc:
        assert "cannot begin with a hyphen" in str(exc)
    else:
        raise AssertionError("leading-hyphen parameter was not rejected")


def test_command_output_is_bounded_while_stream_is_drained() -> None:
    runner = CommandRunner(max_output_bytes=1024, redactor=Redactor([]))
    result = runner.run(
        ["/usr/bin/python3", "-c", "import sys; sys.stdout.write('x' * 200000)"],
        timeout_seconds=5,
    )
    assert result.exit_code == 0
    assert result.stdout_truncated is True
    assert len(result.stdout.encode("utf-8")) < 1200
    assert result.stdout.endswith("[OUTPUT TRUNCATED]")
