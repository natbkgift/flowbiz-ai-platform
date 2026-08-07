# FlowBiz VPS MCP Gateway

Internal, tool-only MCP gateway for bounded operations on a FlowBiz VPS. It is
intended to be reached through **OpenAI Secure MCP Tunnel**, so the VPS does not
need a public MCP port and ChatGPT never receives an SSH private key.

## ChatGPT plan compatibility

Verified on **2026-08-07**: ChatGPT Pro custom MCP connections support read/fetch
use, not full custom MCP write actions. The gateway's read tools can be used from
that surface, but `plan_operation`, `execute_operation`, and `cancel_operation`
require a supported write-capable surface such as eligible ChatGPT
Business/Enterprise/Edu access or a compatible Codex/API client. This is a
product-access limitation, not a reason to weaken the server controls.

`mutation_mode=plan-only` is a gateway safety mode. It means the server may store
immutable operation plans but will not execute them. It does not override the
client plan's MCP permissions.

## Security boundary

This is deliberately **not** an arbitrary SSH or shell server.

- The MCP process runs as the unprivileged `flowbiz-mcp` user.
- A separate root executor listens only on a local Unix socket.
- Every mutation is a fixed `argv` template from root-owned YAML.
- The privileged config is revalidated before each execution: absolute regular
  file, no symlink components, root-owned, and not writable by group/others.
- Executor approval state is kept in a root-owned `0700` directory.
- Privileged executables and their resolved parent directories must be root-owned
  and not writable by group/others.
- User values occupy complete argv elements, are regex-allowlisted, and are never
  interpreted by a shell.
- Plans are immutable, hashed, expiring, audited, and protected against replay.
- Moderate `host-confirmation` actions require the exact plan-bound digest phrase.
  This is a two-step integrity acknowledgement and host confirmation, **not** an
  independent out-of-band human approval gate.
- High/critical actions require a one-time operator code issued locally as root.
  The operator CLI requires a real TTY, displays the exact plan, and requires an
  exact typed approval phrase before issuing the code.
- A code cannot be reissued for the same operation. A lost or expired code
  requires a new plan.
- Output is bounded and redacted; config contains no secrets.
- Mutation mode defaults to `plan-only`; all example actions default to disabled.

## MCP tools

Read-only:

- `gateway_info`
- `list_targets`
- `server_overview`
- `service_status`
- `service_logs`
- `project_revision`
- `healthcheck`
- `operation_status`
- `recent_audit`

Controlled writes:

- `plan_operation`
- `execute_operation`
- `cancel_operation`

There is no `run_command`, `shell`, `ssh`, file-write, secret-read, firewall,
`authorized_keys`, or database-restore tool.

## Architecture

```text
ChatGPT / Codex / API client
      |
      | OpenAI Secure MCP Tunnel (outbound-only from VPS)
      v
flowbiz-vps-mcp-tunnel.service     [User: flowbiz-mcp]
      |
      | stdio MCP child
      v
flowbiz-vps-mcp                    [read + plan + audit]
      |
      | bounded JSON over Unix socket
      v
flowbiz-vps-mcp-executor.service   [User: root]
      |
      | fixed argv from root-owned config; shell=False
      v
systemd / root-owned release scripts
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .

export FLOWBIZ_VPS_MCP_CONFIG="$PWD/config/targets.example.yaml"
flowbiz-vps-mcp-admin check-config
```

The example config is `plan-only` and its actions are disabled. The service name,
project path, health URL, and deployment script are placeholders: replace and
independently verify them against the live VPS before enabling anything.

## VPS installation

```bash
sudo bash scripts/bootstrap.sh
```

The bootstrap is intentionally non-activating. It installs files, creates the
unprivileged user and private state paths, hardens ownership/modes, and installs
systemd units, but it does not start either service.

Initialize the outbound tunnel only after creating a tunnel ID and runtime key in
the OpenAI control plane:

```bash
sudo -u flowbiz-mcp -H env HOME=/var/lib/flowbiz-vps-mcp \
  CONTROL_PLANE_API_KEY='...' \
  /usr/local/bin/tunnel-client init \
    --sample sample_mcp_stdio_local \
    --profile flowbiz-vps \
    --tunnel-id 'TUNNEL_ID' \
    --mcp-command '/opt/flowbiz/vps-mcp/.venv/bin/flowbiz-vps-mcp'

sudo -u flowbiz-mcp -H env HOME=/var/lib/flowbiz-vps-mcp \
  CONTROL_PLANE_API_KEY='...' \
  /usr/local/bin/tunnel-client doctor --profile flowbiz-vps --explain
```

The real runtime key belongs only in `/etc/flowbiz-vps-mcp/tunnel.env` with
`root:root 0600`. Never commit it or pass it as an MCP argument.

## Operator-code flow for high-risk actions

1. A write-capable MCP client calls `plan_operation` and returns `operation_id`
   and `digest`.
2. An authorized VPS operator runs locally in a TTY:

   ```bash
   sudo /opt/flowbiz/vps-mcp/.venv/bin/flowbiz-vps-mcp-admin \
     --config /etc/flowbiz-vps-mcp/config.yaml \
     approve-operation OPERATION_ID DIGEST
   ```

3. The CLI displays target, action, reason, command preview, digest, and expiry.
4. The operator types the exact `ISSUE-FLOWBIZ-OPERATOR-CODE ...` phrase.
5. The CLI prints a short-lived code once.
6. The client calls `execute_operation` with that code.
7. The root executor consumes the code; replay and reissuance are rejected.

A failed, lost, or expired approval requires a new immutable operation plan.

## Production activation checklist

- Keep `/etc/flowbiz-vps-mcp` root-owned and not writable by group/others.
- Keep `/etc/flowbiz-vps-mcp/config.yaml` owned by `root:flowbiz-mcp`, mode `0640`.
- Keep `/etc/flowbiz-vps-mcp/tunnel.env` owned by `root:root`, mode `0600`.
- Keep `/var/lib/flowbiz-vps-mcp-executor` owned by `root:root`, mode `0700`;
  the unprivileged MCP process must not access approval records.
- Use exact service units and exact immutable release scripts; keep every
  privileged executable and parent directory root-owned and non-writable by
  group/others.
- Verify backup, rollback, health, migration, and release provenance independently.
- Start with `mutation_mode=plan-only` and all actions disabled.
- Enable one action at a time only after its exact command and recovery path pass.
- Review audit events after every controlled mutation.
- Do not add an arbitrary command tool later.

## Current scope

This service is a secure baseline. It does not create the OpenAI tunnel ID or
runtime key, and it does not alter the live VPS automatically. Those credentials
must be provisioned through the secure OpenAI control plane and installed directly
on the server, never committed to GitHub or pasted into logs.
