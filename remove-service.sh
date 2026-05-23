#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./remove-service.sh [--service <service_name>] [--delete-state]

Examples:
  ./remove-service.sh --service picasso-repo
  ./remove-service.sh --service picasso-repo --delete-state
EOF
}

SERVICE_NAME="picasso-repo"
DELETE_STATE="false"
PODMAN_BIN="${PODMAN_BIN:-podman}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --delete-state)
      DELETE_STATE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

TS_STATE_VOLUME="${SERVICE_NAME}-tailscale-state"
SSH_HOSTKEYS_VOLUME="${SERVICE_NAME}-ssh-hostkeys"

"$PODMAN_BIN" pod rm -f "$SERVICE_NAME" >/dev/null 2>&1 || true

if [[ "$DELETE_STATE" == "true" ]]; then
  "$PODMAN_BIN" volume rm "$TS_STATE_VOLUME" "$SSH_HOSTKEYS_VOLUME" >/dev/null 2>&1 || true
fi

cat <<EOF

Service removed: $SERVICE_NAME

Tailscale state kept: $([[ "$DELETE_STATE" == "true" ]] && echo "no" || echo "yes")
SSH host keys kept: $([[ "$DELETE_STATE" == "true" ]] && echo "no" || echo "yes")
EOF
