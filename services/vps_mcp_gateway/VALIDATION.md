# Validation record

Date: 2026-08-07 (Asia/Bangkok)

## Local validation completed

- Python source compilation: passed.
- Unit/integration checks: **21 passed**.
- End-to-end Unix-socket test: passed with a fixed `/usr/bin/echo` action.
- Nonzero command evidence test: passed; real exit code retained.
- Bounded-output streaming test: passed; excess output discarded and marked.
- Immutable plan and idempotency tests: passed.
- One-time approval consumption and no-reissuance tests: passed.
- Exact host confirmation and exact operator TTY phrase tests: passed.
- Config shell/placeholder/SSRF/sensitive-parameter/high-risk policy tests: passed.
- Example config command contract: passed; actions disabled and mode `plan-only`.
- Restricted subprocess `PATH` test: passed.
- Redaction tests: passed.
- Bootstrap shell syntax: passed.
- Admin config smoke: passed.
- Python wheel build: passed.
- systemd unit parser reached only the expected build-host warnings that the
  production executables are not installed at their final absolute paths.

## Validation delegated to GitHub CI

The source runtime in this chat did not contain Ruff or the MCP SDK, and its
internal package mirror did not expose those packages. Therefore this record does
not claim a local Ruff pass or a live import against the installed MCP wheel.

The included `VPS MCP Gateway CI` workflow installs the standalone service from
public package sources and runs:

- Ruff with the service's configured rule set;
- all 21 checks;
- actual `mcp==2.0.0` server import and decorator registration;
- bootstrap syntax;
- config smoke;
- wheel build.

The Draft PR must remain unmerged until this workflow passes.

## Not performed

- No SSH connection to `flowbiz-vps` was available from this chat.
- No files were installed on the live VPS.
- No tunnel ID or runtime key was created.
- No systemd service was enabled or started.
- No mutation action was enabled.
- No production command, backup, migration, deploy, restart, or rollback ran.

These are intentional release gates, not implied completions.
