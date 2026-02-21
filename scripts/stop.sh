#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .run/app.pid ]]; then
  APP_PID="$(cat .run/app.pid)"
  if kill -0 "$APP_PID" >/dev/null 2>&1; then
    echo "[stop] Stopping app process $APP_PID"
    kill "$APP_PID" || true
  fi
  rm -f .run/app.pid
fi

echo "[stop] Stopping infrastructure services"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml down --remove-orphans
else
  echo "[stop] docker compose not available; skipped infra shutdown" >&2
fi

echo "[stop] Done"
