#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/bootstrap.sh" >&2
  exit 1
fi

for command in python3 rsync systemctl useradd install find chown chmod; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

python3 - <<'PY'
import sys

version = sys.version_info[:2]
if not ((3, 11) <= version < (3, 14)):
    raise SystemExit(
        f"Python 3.11-3.13 is required; found {sys.version_info.major}.{sys.version_info.minor}"
    )
PY

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Python venv support is required (for Ubuntu, install python3-venv)." >&2
  exit 1
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALL_DIR=/opt/flowbiz/vps-mcp
CONFIG_DIR=/etc/flowbiz-vps-mcp
GATEWAY_STATE=/var/lib/flowbiz-vps-mcp
EXECUTOR_STATE=/var/lib/flowbiz-vps-mcp-executor
RUN_DIR=/run/flowbiz-vps-mcp

secure_install_tree() {
  chown -R root:flowbiz-mcp "$INSTALL_DIR"
  find "$INSTALL_DIR" -type d -exec chmod 0750 {} +
  find "$INSTALL_DIR" -type f -exec chmod 0640 {} +
  if [[ -d "$INSTALL_DIR/.venv/bin" ]]; then
    find "$INSTALL_DIR/.venv/bin" -maxdepth 1 -type f -exec chmod 0750 {} +
  fi
  if [[ -f "$INSTALL_DIR/scripts/bootstrap.sh" ]]; then
    chmod 0750 "$INSTALL_DIR/scripts/bootstrap.sh"
  fi
}

if ! id flowbiz-mcp >/dev/null 2>&1; then
  useradd --system --home-dir "$GATEWAY_STATE" --create-home --shell /usr/sbin/nologin flowbiz-mcp
fi

install -d -m 0750 -o root -g flowbiz-mcp "$INSTALL_DIR" "$CONFIG_DIR"
install -d -m 0750 -o flowbiz-mcp -g flowbiz-mcp "$GATEWAY_STATE"
install -d -m 0700 -o root -g root "$EXECUTOR_STATE"
install -d -m 0750 -o root -g flowbiz-mcp "$RUN_DIR"

rsync -a --delete \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  "$SOURCE_DIR/" "$INSTALL_DIR/"
secure_install_tree

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" --disable-pip-version-check install "$INSTALL_DIR"
secure_install_tree

if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  install -m 0640 -o root -g flowbiz-mcp \
    "$INSTALL_DIR/config/targets.example.yaml" "$CONFIG_DIR/config.yaml"
  echo "Installed disabled/example config at $CONFIG_DIR/config.yaml"
else
  chown root:flowbiz-mcp "$CONFIG_DIR/config.yaml"
  chmod 0640 "$CONFIG_DIR/config.yaml"
fi

if [[ ! -f "$CONFIG_DIR/tunnel.env" ]]; then
  install -m 0600 -o root -g root \
    "$INSTALL_DIR/deploy/systemd/tunnel.env.example" "$CONFIG_DIR/tunnel.env"
  echo "Installed placeholder tunnel env at $CONFIG_DIR/tunnel.env"
else
  chown root:root "$CONFIG_DIR/tunnel.env"
  chmod 0600 "$CONFIG_DIR/tunnel.env"
fi

install -m 0644 "$INSTALL_DIR/deploy/systemd/flowbiz-vps-mcp-executor.service" \
  /etc/systemd/system/flowbiz-vps-mcp-executor.service
install -m 0644 "$INSTALL_DIR/deploy/systemd/flowbiz-vps-mcp-tunnel.service" \
  /etc/systemd/system/flowbiz-vps-mcp-tunnel.service

systemctl daemon-reload

cat <<'INSTRUCTIONS'

Installation files are in place. Services were NOT enabled or started.

Required gates before start:
1. Edit /etc/flowbiz-vps-mcp/config.yaml. Replace the example unit/path/script
   values with verified values for this VPS. Keep every action disabled.
2. Install OpenAI tunnel-client at /usr/local/bin/tunnel-client.
3. Initialize the profile as the unprivileged account (replace TUNNEL_ID and key):

   sudo -u flowbiz-mcp -H env HOME=/var/lib/flowbiz-vps-mcp \
     CONTROL_PLANE_API_KEY='...' \
     /usr/local/bin/tunnel-client init \
       --sample sample_mcp_stdio_local \
       --profile flowbiz-vps \
       --tunnel-id 'TUNNEL_ID' \
       --mcp-command '/opt/flowbiz/vps-mcp/.venv/bin/flowbiz-vps-mcp'

4. Put only the runtime key in /etc/flowbiz-vps-mcp/tunnel.env (0600 root:root).
5. Validate:

   /opt/flowbiz/vps-mcp/.venv/bin/flowbiz-vps-mcp-admin \
     --config /etc/flowbiz-vps-mcp/config.yaml check-config

   sudo -u flowbiz-mcp -H env HOME=/var/lib/flowbiz-vps-mcp \
     CONTROL_PLANE_API_KEY='...' \
     /usr/local/bin/tunnel-client doctor --profile flowbiz-vps --explain

6. Start with mutation_mode=plan-only and all actions disabled:

   systemctl enable --now flowbiz-vps-mcp-executor.service
   systemctl enable --now flowbiz-vps-mcp-tunnel.service

Do not change mutation_mode to enabled until backup, rollback, root-owned action
scripts, exact target commands, and independent recovery tests have passed. Enable
only one action at a time.
INSTRUCTIONS
