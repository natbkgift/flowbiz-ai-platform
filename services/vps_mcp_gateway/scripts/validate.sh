#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

cleanup() {
  rm -rf build .pytest_cache .ruff_cache src/*.egg-info
  find src checks -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
}
trap cleanup EXIT
cleanup

python -m compileall -q src checks
python -m ruff check .
python -m pytest
bash -n scripts/bootstrap.sh

FLOWBIZ_VPS_MCP_CONFIG="$ROOT_DIR/config/targets.example.yaml" \
  python -m flowbiz_vps_mcp.cli check-config >/dev/null

python - <<'PY'
from flowbiz_vps_mcp.server import mcp

assert mcp is not None
print("mcp-server-import-ok")
PY

WHEEL_DIR=$(mktemp -d)
trap 'rm -rf "$WHEEL_DIR"; cleanup' EXIT
python -m pip wheel --disable-pip-version-check --no-deps --no-build-isolation \
  . -w "$WHEEL_DIR" >/dev/null
ls "$WHEEL_DIR"/flowbiz_vps_mcp_gateway-*.whl >/dev/null
