#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "[start] Created .env from .env.example"
  else
    echo "[start] ERROR: .env is missing and .env.example was not found." >&2
    exit 1
  fi
fi

export PYTHONUNBUFFERED=1

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "[start] Starting infrastructure services"
  docker compose -f infra/docker-compose.yml up -d db redis qdrant

  echo "[start] Running migrations"
  bash infra/scripts/migrate.sh

  echo "[start] Seeding demo campaign"
  bash infra/scripts/seed_demo.sh
else
  echo "[start] docker compose unavailable; skipping infra start/migrate/seed" >&2
fi

echo "[start] Installing Python dependencies"
python -m pip install -r requirements-dev.txt >/dev/null
python - <<'PY'
import tomllib
from pathlib import Path
import subprocess

data = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
deps = data.get('project', {}).get('dependencies', [])
if deps:
    subprocess.check_call(['python', '-m', 'pip', 'install', *deps])
PY

if [[ "${RUN_FOREGROUND:-0}" == "1" ]]; then
  echo "[start] Running app in foreground at http://localhost:8000"
  exec env PORT=8000 python app.py
fi

mkdir -p .run
if [[ -f .run/app.pid ]] && kill -0 "$(cat .run/app.pid)" >/dev/null 2>&1; then
  echo "[start] App already running with PID $(cat .run/app.pid)"
  exit 0
fi

echo "[start] Launching app in background"
nohup env PORT=8000 python app.py > .run/app.log 2>&1 &
echo $! > .run/app.pid

sleep 2
if kill -0 "$(cat .run/app.pid)" >/dev/null 2>&1; then
  echo "[start] Stack is up. Dashboard: http://localhost:8000"
  echo "[start] Use scripts/stop.sh to stop all services."
else
  echo "[start] ERROR: app failed to start. Check .run/app.log" >&2
  exit 1
fi
