#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_REPOSITORY = "natbkgift/flowbiz-ai-platform"
EXPECTED_COMMAND = "python scripts/ci/run_local_ci.py"
EXPECTED_GATE_NAMES = [
    "worktree-clean",
    "upstream-synchronized",
    "diff-check",
    "ruff-lint",
    "pytest-suite",
]
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class LocalCiEvidenceError(ValueError):
    """Raised when exact-head Local CI evidence is missing or invalid."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LocalCiEvidenceError(message)


def load_summary(path: Path) -> tuple[Path, dict[str, Any]]:
    summary_path = path / "summary.json" if path.is_dir() else path
    require(summary_path.name == "summary.json", "evidence path must resolve to summary.json")
    require(summary_path.is_file(), f"summary not found: {summary_path}")
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise LocalCiEvidenceError(f"invalid summary JSON: {exc}") from exc
    require(isinstance(data, dict), "summary root must be a JSON object")
    return summary_path, data


def validate_evidence(path: Path, expected_head: str | None = None) -> str:
    summary_path, data = load_summary(path)

    require(data.get("schema_version") == 1, "schema_version must be 1")
    require(data.get("repository") == EXPECTED_REPOSITORY, f"repository does not match {EXPECTED_REPOSITORY}")
    require(data.get("mode") == "pr", "mode must be pr")
    require(data.get("status") == "PASS", "Local CI status must be PASS")

    tested_head = data.get("tested_head")
    base_sha = data.get("base_sha")
    require(isinstance(tested_head, str) and bool(SHA_PATTERN.fullmatch(tested_head)), "tested_head must be a full SHA")
    require(isinstance(base_sha, str) and bool(SHA_PATTERN.fullmatch(base_sha)), "base_sha must be a full SHA")
    if expected_head is not None:
        require(bool(SHA_PATTERN.fullmatch(expected_head)), "--expected-head must be a full SHA")
        require(tested_head == expected_head, f"tested_head {tested_head} does not match expected head {expected_head}")

    branch = data.get("branch")
    upstream = data.get("upstream")
    require(isinstance(branch, str) and bool(branch.strip()), "branch is required")
    require(isinstance(upstream, str) and upstream not in {"", "UNRESOLVED"}, "upstream must be resolved")
    require(data.get("ahead") == 0, "local branch must not be ahead of upstream")
    require(data.get("behind") == 0, "local branch must not be behind upstream")
    require(data.get("worktree_clean") is True, "worktree must be clean")

    gates = data.get("gates")
    require(isinstance(gates, list), "gates must be a list")
    gates_list = gates if isinstance(gates, list) else []
    require([gate.get("name") for gate in gates_list if isinstance(gate, dict)] == EXPECTED_GATE_NAMES, f"gate names or order do not match {EXPECTED_GATE_NAMES}")
    require(data.get("gate_count") == len(EXPECTED_GATE_NAMES), f"gate_count must be {len(EXPECTED_GATE_NAMES)}")
    require(data.get("gates_passed") == len(EXPECTED_GATE_NAMES), f"gates_passed must be {len(EXPECTED_GATE_NAMES)}")
    for gate in gates_list:
        require(isinstance(gate, dict) and gate.get("status") == "PASS", f"gate {gate.get('name') if isinstance(gate, dict) else gate} did not pass")
        require(isinstance(gate, dict) and gate.get("exit_code") == 0, f"gate {gate.get('name') if isinstance(gate, dict) else gate} exit_code must be 0")

    expected_evidence_dir = f"artifacts/local-ci/{tested_head}/"
    require(data.get("command") == EXPECTED_COMMAND, "Local CI command does not match canonical command")
    require(data.get("evidence_dir") == expected_evidence_dir, "evidence_dir must be exact-head scoped")
    require(data.get("limitations") == "none", "PASS evidence must declare limitations: none")

    for timestamp_field in ("started_at", "finished_at"):
        timestamp = data.get(timestamp_field)
        is_utc = isinstance(timestamp, str) and timestamp.endswith(("Z", "+00:00"))
        require(is_utc, f"{timestamp_field} must use a UTC timestamp")

    proof_path = summary_path.with_name("proof.txt")
    require(proof_path.is_file(), f"proof not found: {proof_path}")
    expected_proof = "\n".join(
        [
            f"TESTED HEAD: {tested_head}",
            f"BASE SHA: {base_sha}",
            f"LOCAL CI: PASS {len(EXPECTED_GATE_NAMES)}/{len(EXPECTED_GATE_NAMES)}",
            f"COMMAND: {EXPECTED_COMMAND}",
            f"EVIDENCE: {expected_evidence_dir}",
            "LIMITATIONS: none",
        ]
    )
    actual_proof = proof_path.read_text(encoding="utf-8-sig").strip().replace("\r\n", "\n")
    require(actual_proof == expected_proof, "proof.txt does not match canonical exact-head proof block")

    return str(tested_head)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate exact-head FlowBiz AI Platform Local CI evidence.")
    parser.add_argument("evidence", type=Path, help="Evidence directory or summary.json path")
    parser.add_argument("--expected-head", help="Expected full PR head SHA")
    args = parser.parse_args()

    try:
        tested_head = validate_evidence(args.evidence, args.expected_head)
    except LocalCiEvidenceError as exc:
        print(f"INVALID: {exc}")
        return 1

    print(f"VALID: exact-HEAD Local CI evidence for {tested_head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
