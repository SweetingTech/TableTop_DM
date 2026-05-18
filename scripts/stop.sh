#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="docker"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    *)
      echo "[stop] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

APP_PID_FILE=".local-run/app.pid"
DEPS_PROVIDER_FILE=".local-run/deps-provider"
DEPS_STARTED_FILE=".local-run/deps-started-by-start"

if [[ -f "$APP_PID_FILE" ]]; then
  PID="$(cat "$APP_PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID" || true
    sleep 1
    if kill -0 "$PID" >/dev/null 2>&1; then
      kill -9 "$PID" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$APP_PID_FILE"
fi

provider=""
[[ -f "$DEPS_PROVIDER_FILE" ]] && provider="$(cat "$DEPS_PROVIDER_FILE")"
started_by_start=0
[[ -f "$DEPS_STARTED_FILE" ]] && started_by_start=1

if [[ "$MODE" == "docker" || ( "$provider" == "docker" && "$started_by_start" == "1" ) ]]; then
  if bash scripts/docker_runtime_available.sh; then
    if [[ ! -f .env ]]; then
      cp .env.example .env
    fi
    docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/infra/docker-compose.yml" down --remove-orphans
  fi
fi

rm -f "$DEPS_PROVIDER_FILE" "$DEPS_STARTED_FILE"
echo "[stop] Stopped mode=$MODE"
