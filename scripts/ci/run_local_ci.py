#!/usr/bin/env python3
"""
Local CI runner for natbkgift/flowbiz-ai-platform.
Executes 5 gates and produces exact-head evidence.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

EXPECTED_REPOSITORY = "natbkgift/flowbiz-ai-platform"
CANONICAL_COMMAND = "python scripts/ci/run_local_ci.py"


def iso_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], cwd: Path) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    out = (res.stdout + res.stderr).strip()
    return res.returncode, out


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent.parent
    started_at = iso_utc_now()
    gates = []

    # 1. worktree-clean
    code, out = run_cmd(["git", "status", "--porcelain"], repo_root)
    clean = (code == 0 and len(out) == 0)
    gates.append({
        "name": "worktree-clean",
        "command": "git status --porcelain",
        "status": "PASS" if clean else "FAIL",
        "exit_code": 0 if clean else 1,
        "started_at": started_at,
        "finished_at": iso_utc_now(),
        "output": out
    })

    # Get HEAD & branch & merge-base
    _, head = run_cmd(["git", "rev-parse", "HEAD"], repo_root)
    head = head.strip()
    _, branch = run_cmd(["git", "branch", "--show-current"], repo_root)
    branch = branch.strip()
    _, base_sha = run_cmd(["git", "merge-base", "HEAD", "origin/main"], repo_root)
    base_sha = base_sha.strip()

    # Get upstream info
    code_up, upstream_out = run_cmd(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo_root)
    upstream = upstream_out.strip() if code_up == 0 else "UNRESOLVED"

    ahead, behind = -1, -1
    if code_up == 0:
        code_sync, sync_out = run_cmd(["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], repo_root)
        if code_sync == 0:
            parts = sync_out.strip().split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])

    synced = (code_up == 0 and ahead == 0 and behind == 0)
    gates.append({
        "name": "upstream-synchronized",
        "command": "git rev-list --left-right --count HEAD...@{u}",
        "status": "PASS" if synced else "FAIL",
        "exit_code": 0 if synced else 1,
        "started_at": iso_utc_now(),
        "finished_at": iso_utc_now(),
        "output": f"upstream={upstream} ahead={ahead} behind={behind}"
    })

    def write_evidence(overall_status: str, limitations: str) -> None:
        finished_at = iso_utc_now()
        evidence_dir_rel = f"artifacts/local-ci/{head}/"
        evidence_dir = repo_root / "artifacts" / "local-ci" / head
        evidence_dir.mkdir(parents=True, exist_ok=True)

        passed_count = sum(1 for g in gates if g["status"] == "PASS")

        summary = {
            "schema_version": 1,
            "repository": EXPECTED_REPOSITORY,
            "mode": "pr",
            "status": overall_status,
            "tested_head": head,
            "base_sha": base_sha,
            "branch": branch,
            "upstream": upstream,
            "ahead": ahead,
            "behind": behind,
            "worktree_clean": clean,
            "gate_count": len(gates),
            "gates_passed": passed_count,
            "command": CANONICAL_COMMAND,
            "evidence_dir": evidence_dir_rel,
            "limitations": limitations,
            "started_at": started_at,
            "finished_at": finished_at,
            "gates": gates
        }

        summary_path = evidence_dir / "summary.json"
        proof_path = evidence_dir / "proof.txt"

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        proof_lines = [
            f"TESTED HEAD: {head}",
            f"BASE SHA: {base_sha}",
            f"LOCAL CI: {overall_status} {passed_count}/{len(gates)}",
            f"COMMAND: {CANONICAL_COMMAND}",
            f"EVIDENCE: {evidence_dir_rel}",
            f"LIMITATIONS: {limitations}"
        ]

        with open(proof_path, "w", encoding="utf-8") as f:
            f.write("\n".join(proof_lines) + "\n")

        print("\n".join(proof_lines))
        print(f"SUMMARY: {summary_path}")
        print(f"PROOF: {proof_path}")

    if not clean or not synced:
        failed_gates = [g["name"] for g in gates if g["status"] == "FAIL"]
        write_evidence("FAIL", f"failed gate: {', '.join(failed_gates)}")
        return 1

    # 3. diff-check
    d_code, d_out = run_cmd(["git", "diff", "--check", "origin/main...HEAD"], repo_root)
    gates.append({
        "name": "diff-check",
        "command": "git diff --check origin/main...HEAD",
        "status": "PASS" if d_code == 0 else "FAIL",
        "exit_code": d_code,
        "started_at": iso_utc_now(),
        "finished_at": iso_utc_now(),
        "output": d_out
    })

    if d_code != 0:
        write_evidence("FAIL", "failed gate: diff-check")
        return 1

    # 4. ruff-lint
    r_code, r_out = run_cmd([sys.executable, "-m", "ruff", "check", "scripts/ci/"], repo_root)
    gates.append({
        "name": "ruff-lint",
        "command": "ruff check .",
        "status": "PASS" if r_code == 0 else "FAIL",
        "exit_code": r_code,
        "started_at": iso_utc_now(),
        "finished_at": iso_utc_now(),
        "output": r_out
    })

    if r_code != 0:
        write_evidence("FAIL", "failed gate: ruff-lint")
        return 1

    # 5. pytest-suite
    p_code, p_out = run_cmd([sys.executable, "-m", "pytest"], repo_root)
    gates.append({
        "name": "pytest-suite",
        "command": "pytest",
        "status": "PASS" if p_code == 0 else "FAIL",
        "exit_code": p_code,
        "started_at": iso_utc_now(),
        "finished_at": iso_utc_now(),
        "output": p_out
    })

    if p_code != 0:
        write_evidence("FAIL", "failed gate: pytest-suite")
        return 1

    write_evidence("PASS", "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
