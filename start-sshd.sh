#!/usr/bin/env bash
set -euo pipefail

AUTHORIZED_KEYS_FILE="${AUTHORIZED_KEYS_FILE:-/authorized_keys}"
WEB_PORT="${WEB_PORT:-80}"

mkdir -p /root/.ssh /run/sshd /repository
chmod 700 /root/.ssh

if [[ -f "$AUTHORIZED_KEYS_FILE" ]]; then
  cp "$AUTHORIZED_KEYS_FILE" /root/.ssh/authorized_keys
elif [[ -n "${AUTHORIZED_KEYS:-}" ]]; then
  printf '%s\n' "$AUTHORIZED_KEYS" > /root/.ssh/authorized_keys
else
  echo "No SSH authorized keys configured. Mount a key file or set AUTHORIZED_KEYS." >&2
  exit 1
fi

chmod 600 /root/.ssh/authorized_keys

cat >/etc/ssh/sshd_config <<'EOF'
Port 22
ListenAddress 0.0.0.0
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowTcpForwarding no
X11Forwarding no
Subsystem sftp internal-sftp
EOF

/usr/sbin/sshd -D -e &
SSHD_PID="$!"

cleanup() {
  kill "$SSHD_PID" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

exec /usr/local/bin/web-status.py
