# Security model

## Objective

Expose a small set of operational capabilities without handing an AI client an
SSH key, arbitrary shell, unrestricted `sudo`, filesystem write tool, or direct
production database access.

## Trust boundaries

1. **OpenAI Secure MCP Tunnel** carries MCP traffic outbound from the VPS. No
   public MCP listener is required.
2. **Unprivileged gateway** (`flowbiz-mcp`) performs bounded reads, validates
   plans, stores audit records, and sends a fixed JSON protocol over a Unix
   socket.
3. **Privileged executor** (`root`) reloads and independently validates the
   root-owned configuration, command, parameters, digest, approval, executable,
   and replay state before starting a process.
4. **Root-owned action scripts** are the final privileged boundary. They must
   implement their own exact-release, backup, migration, health, and rollback
   contracts.

The gateway process is not trusted to choose a command. It may only request an
operation identified by target/action/parameters, and the executor reconstructs
the command from its own current root-owned configuration.

## Enforced invariants

- No shell interpreter may be configured as an executable.
- Executables use absolute paths and are explicitly allowlisted.
- Privileged executables are root-owned, executable, and not writable by
  group/others; resolved parent directories are also root-controlled.
- Configuration has no symlink components, is root-owned, and is not writable by
  group/others.
- Executor state is in a root-owned directory with no group/other access.
- Parameters occupy a complete `argv` element, match an anchored allowlist
  pattern, have bounded length, cannot have sensitive names, and cannot begin
  with `-`.
- `shell=False`; stdin is closed; environment and `PATH` are replaced with fixed
  values.
- stdout and stderr are continuously drained into bounded in-memory captures;
  excess output is discarded and marked truncated.
- Health requests ignore proxy environment variables, reject redirects, and use
  fixed configured URLs whose hosts are allowlisted.
- Plans include operation ID, target, action, parameters, reason, rendered argv,
  and configuration fingerprint in a SHA-256 digest.
- Operation plans and operator codes expire.
- Gateway and executor stores reject replay.
- Operator approval codes are one-time and cannot be reissued for an operation.
- Command output and errors pass through configured redaction before returning to
  the client or audit surface.

## Approval modes

### Host confirmation

For moderate actions only. The client must return the exact
`APPROVE-FLOWBIZ-OPERATION <operation> <digest-prefix>` phrase generated from the
stored plan. This binds execution to the reviewed plan and allows the MCP host to
apply its own write confirmation. It is not an independent human approval.

### Operator code

Required for high and critical actions. A root operator on the VPS must:

- use an interactive TTY;
- review target, action, reason, command preview, digest, and expiry;
- type the exact local approval phrase;
- transfer the resulting short-lived code to the single execution call.

A wrong code, lost code, expired code, failed approval, or consumed code requires
a new immutable operation plan.

## Secrets

- Do not put secrets in YAML, action parameters, reasons, or idempotency keys.
- The Secure MCP Tunnel runtime key belongs only in the root-owned `0600`
  environment file.
- Do not expose `.env`, private keys, database URLs, OAuth tokens, or API keys as
  read tools.
- Redaction is defense in depth, not permission to intentionally log secrets.

## Failure behavior

The design is fail-closed:

- configuration drift invalidates a plan;
- missing executor socket prevents execution;
- disabled mutation mode or disabled action prevents execution;
- unknown target/action/parameter is rejected;
- approval failure records a failed executor attempt and requires a new plan;
- nonzero exit, timeout, protocol rejection, or missing executor evidence is
  recorded as failed;
- success is reported only from a persisted executor result with exit code zero.

## Explicit non-goals

The service does not provide:

- arbitrary SSH or command execution;
- interactive terminals;
- generic file reads or writes;
- secret retrieval;
- firewall, user, SSH-key, or package-management tools;
- direct SQL, database restore, or destructive migration tools;
- automatic discovery of services or deployment commands;
- automatic production activation.

## Activation gates

Before enabling one mutation action:

1. Verify exact target path, systemd unit, health URL, and executable on the VPS.
2. Verify the executable and all parent ownership/modes.
3. Prove immutable release provenance.
4. Complete backup and restore rehearsal.
5. Complete migration and rollback rehearsal.
6. Prove bounded health and post-deploy checks.
7. Start in `plan-only` with every action disabled.
8. Enable one action, observe one controlled execution, and inspect both stores
   and system logs.
9. Disable immediately if audit evidence is incomplete.
