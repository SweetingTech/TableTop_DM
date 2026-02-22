#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .run/app_local.pid ]]; then
  APP_PID="$(cat .run/app_local.pid)"
  if kill -0 "$APP_PID" >/dev/null 2>&1; then
    echo "[stop_local] Stopping app process $APP_PID"
    kill "$APP_PID" || true
  fi
  rm -f .run/app_local.pid
else
    echo "[stop_local] No .run/app_local.pid found."
fi

echo "[stop_local] Done"
