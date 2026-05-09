#!/usr/bin/env bash
set -euo pipefail

# Manual-only helper. It is intentionally gated and must not be auto-run by CI.
ROOT="${1:-/opt/flowbiz-ai-platform}"

if [[ "${CONFIRM_PLATFORM_PERMISSION_REMEDIATION:-}" != "apply" ]]; then
  echo "Dry run only. Re-run with CONFIRM_PLATFORM_PERMISSION_REMEDIATION=apply."
  echo "Target root: ${ROOT}"
  find "${ROOT}" -maxdepth 1 -name '.env.backup*' -print 2>/dev/null || true
  exit 2
fi

if [[ -f "${ROOT}/.env" ]]; then
  chmod 600 "${ROOT}/.env"
fi

find "${ROOT}/platform_data" -maxdepth 1 -type f -name '*.db*' -exec chmod 600 {} \; \
  2>/dev/null || true

find "${ROOT}" -maxdepth 1 -type f -name '*bootstrap*api-key*.txt' -exec chmod 600 {} \; \
  2>/dev/null || true

echo "Permission remediation applied. Move .env.backup* files out of the active path manually."
