#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./stop-service.sh [--service <service_name>]

Example:
  ./stop-service.sh --service picasso-repo
EOF
}

SERVICE_NAME="picasso-repo"
PODMAN_BIN="${PODMAN_BIN:-podman}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE_NAME="${2:-}"
      shift 2
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

"$PODMAN_BIN" pod stop "$SERVICE_NAME"

cat <<EOF

Service stopped: $SERVICE_NAME

To start again:
  $PODMAN_BIN pod start $SERVICE_NAME

To recreate with a different configuration:
  $PODMAN_BIN pod rm -f $SERVICE_NAME
EOF
