#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./create-service.sh [--authkey <ts_authkey>] [options]

Examples:
  ./create-service.sh --authkey tskey-auth-xxxxx
  ./create-service.sh --service picasso-repo --data-dir ~/Documents/PiCASSO_Repository
  ./create-service.sh --port 80

Defaults:
  --service               picasso-repo
  --image                 localhost/picasso-repo-app:latest
  --port                  80
  --data-dir              ~/Documents/PiCASSO_Repository
  --authorized-keys-file  ~/.ssh/id_ed25519.pub

Options:
  --service <name>               Pod and Tailscale hostname
  --authkey <key>                Tailscale auth key (required only on first creation)
  --image <name>                 App image name
  --port <port>                  Web status port inside the pod
  --data-dir <path>              Host directory exposed through SSH/SFTP at /repository
  --authorized-keys-file <path>  Public keys allowed to connect as root
  -h, --help                     Show this help

Environment variables:
  CONTAINERFILE                  Containerfile used for the build step (default: ./Containerfile)
  PODMAN_BIN                     Podman binary to use (default: podman)
EOF
}

SERVICE_NAME="picasso-repo"
TS_AUTHKEY=""
IMAGE_NAME=""
APP_PORT="80"
DATA_DIR_HOST="${HOME}/Documents/PiCASSO_Repository"
AUTHORIZED_KEYS_FILE="${HOME}/.ssh/id_ed25519.pub"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --authkey)
      TS_AUTHKEY="${2:-}"
      shift 2
      ;;
    --image)
      IMAGE_NAME="${2:-}"
      shift 2
      ;;
    --port)
      APP_PORT="${2:-}"
      shift 2
      ;;
    --data-dir)
      DATA_DIR_HOST="${2:-}"
      shift 2
      ;;
    --authorized-keys-file)
      AUTHORIZED_KEYS_FILE="${2:-}"
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

if [[ -z "$IMAGE_NAME" ]]; then
  IMAGE_NAME="localhost/${SERVICE_NAME}-app:latest"
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINERFILE="${CONTAINERFILE:-Containerfile}"
PODMAN_BIN="${PODMAN_BIN:-podman}"

mkdir -p "$DATA_DIR_HOST"
DATA_DIR_HOST="$(cd "$(dirname "$DATA_DIR_HOST")" && pwd)/$(basename "$DATA_DIR_HOST")"

if [[ ! -f "$AUTHORIZED_KEYS_FILE" ]]; then
  echo "Authorized keys file not found: $AUTHORIZED_KEYS_FILE" >&2
  exit 1
fi
AUTHORIZED_KEYS_FILE="$(cd "$(dirname "$AUTHORIZED_KEYS_FILE")" && pwd)/$(basename "$AUTHORIZED_KEYS_FILE")"

TS_STATE_VOLUME="${SERVICE_NAME}-tailscale-state"
APP_CONTAINER="app-${SERVICE_NAME}"
TS_CONTAINER="ts-${SERVICE_NAME}"

run_podman() {
  "$PODMAN_BIN" "$@"
}

if [[ ! -f "$PROJECT_DIR/$CONTAINERFILE" && ! -f "$CONTAINERFILE" ]]; then
  echo "Containerfile not found: $CONTAINERFILE" >&2
  exit 1
fi

HAS_TS_STATE="false"
if run_podman volume inspect "$TS_STATE_VOLUME" >/dev/null 2>&1; then
  HAS_TS_STATE="true"
fi

if [[ -z "$TS_AUTHKEY" && "$HAS_TS_STATE" != "true" ]]; then
  echo "--authkey is required when creating $SERVICE_NAME for the first time." >&2
  usage
  exit 1
fi

echo "Building image $IMAGE_NAME..."
run_podman build -t "$IMAGE_NAME" -f "$CONTAINERFILE" "$PROJECT_DIR"

echo "Creating persistent volumes..."
run_podman volume create "$TS_STATE_VOLUME" >/dev/null 2>&1 || true

echo "Removing previous pod, if it exists..."
run_podman pod rm -f "$SERVICE_NAME" >/dev/null 2>&1 || true

echo "Creating pod $SERVICE_NAME..."
run_podman pod create --name "$SERVICE_NAME" >/dev/null

app_args=(
  run -d
  --pod "$SERVICE_NAME"
  --name "$APP_CONTAINER"
  --security-opt label=disable
  -e "WEB_PORT=$APP_PORT"
  -e "REPOSITORY_DIR=/repository"
  -v "${DATA_DIR_HOST}:/repository:Z"
  -v "${AUTHORIZED_KEYS_FILE}:/authorized_keys:ro"
)

if [[ "$APP_PORT" =~ ^[0-9]+$ ]] && (( APP_PORT < 1024 )); then
  app_args+=(--cap-add NET_BIND_SERVICE)
fi

app_args+=("$IMAGE_NAME")

echo "Starting SSH/web container $APP_CONTAINER..."
run_podman "${app_args[@]}" >/dev/null

echo "Starting Tailscale sidecar $TS_CONTAINER..."
ts_args=(
  run -d
  --pod "$SERVICE_NAME"
  --name "$TS_CONTAINER"
  --cap-add NET_ADMIN
  --cap-add NET_RAW
  --device /dev/net/tun
  -v "${TS_STATE_VOLUME}:/var/lib/tailscale:Z"
  -e TS_STATE_DIR=/var/lib/tailscale
  -e TS_HOSTNAME="$SERVICE_NAME"
)

if [[ -n "$TS_AUTHKEY" ]]; then
  ts_args+=(-e "TS_AUTHKEY=$TS_AUTHKEY")
fi

ts_args+=(docker.io/tailscale/tailscale:latest)
run_podman "${ts_args[@]}" >/dev/null

cat <<EOF

Service created.

Pod:                  $SERVICE_NAME
Application image:    $IMAGE_NAME
SSH container:        $APP_CONTAINER
Tailscale container:  $TS_CONTAINER
Web port:             $APP_PORT
Repository dir:       $DATA_DIR_HOST
Authorized keys file: $AUTHORIZED_KEYS_FILE
TS state volume:      $TS_STATE_VOLUME
Tailscale authkey:    $([[ -n "$TS_AUTHKEY" ]] && echo "provided" || echo "reused existing state")

Checks:
  $PODMAN_BIN pod ps
  $PODMAN_BIN ps
  $PODMAN_BIN logs $APP_CONTAINER
  $PODMAN_BIN logs $TS_CONTAINER

SSH:
  http://$SERVICE_NAME/
  ssh root@$SERVICE_NAME
  rsync -av ./ root@$SERVICE_NAME:/repository/

Cleanup:
  $PODMAN_BIN pod rm -f $SERVICE_NAME
  $PODMAN_BIN volume rm $TS_STATE_VOLUME
EOF
