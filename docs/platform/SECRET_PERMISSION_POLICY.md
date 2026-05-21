# Platform Secret Permission Policy

## Required Permissions

Sensitive runtime files must not be readable by group or other users.

- `.env`: `600`
- `.env.backup.*`: must not exist in the active repo/runtime path
- SQLite DB files under `platform_data`: `600` or restricted owner/group
  equivalent
- Bootstrap admin key file: `600`

## Read-Only Preflight

Use:

```bash
python scripts/check_platform_file_permissions.py --root /opt/flowbiz-ai-platform
```

The script reports only:

- path
- file kind
- status
- POSIX mode when available
- remediation message

It does not open or print file contents.

## Manual Remediation Helper

The helper script is intentionally gated:

```bash
CONFIRM_PLATFORM_PERMISSION_REMEDIATION=apply \
  scripts/remediate_platform_file_permissions.sh /opt/flowbiz-ai-platform
```

Do not run this automatically from CI or deployment hooks. Review findings first.
The helper does not remove `.env.backup.*`; those files must be moved out of the
active runtime path manually after confirming the operational backup process.

## Operator Rules

- Never paste `.env` values into chat, tickets, docs, logs, or PR comments.
- Never print API keys, tokens, private keys, certificates, or database contents.
- Prefer passing secrets through environment variables or a secret manager.
- Rotate any secret that may have been exposed in terminal output or logs.
