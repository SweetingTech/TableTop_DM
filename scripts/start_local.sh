#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "[start_local] Created .env from .env.example"
  else
    echo "[start_local] ERROR: .env is missing and .env.example was not found." >&2
    exit 1
  fi
fi

# Export env vars from .env
set -a
source .env
set +a

export PYTHONUNBUFFERED=1
export PORT="${PORT:-8000}"

echo "[start_local] Checking DATABASE_URL..."
if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[start_local] ERROR: DATABASE_URL is not set." >&2
    exit 1
fi

# Install dependencies if needed (using pip install -r requirements-dev.txt is standard practice for dev)
echo "[start_local] Ensuring dependencies..."
if ! python -m pip install -r requirements-dev.txt >/dev/null 2>&1; then
    echo "[start_local] WARNING: Failed to install requirements-dev.txt. Assuming already installed or handled externally."
fi

python - <<'PY'
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("Warning: tomllib/tomli not found, skipping pyproject.toml dependency check.")
        sys.exit(0)

try:
    data = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    deps = data.get('project', {}).get('dependencies', [])
    if deps:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception as e:
    print(f"Warning: could not install deps from pyproject.toml: {e}")
PY

echo "[start_local] Running migrations..."
if ! python infra/migrate.py; then
    echo "[start_local] ERROR: Migrations failed. Is Postgres running at $DATABASE_URL?" >&2
    exit 1
fi

echo "[start_local] Seeding demo..."
if ! python infra/seed.py; then
    echo "[start_local] ERROR: Seeding failed." >&2
    exit 1
fi

if [[ "${RUN_FOREGROUND:-0}" == "1" ]]; then
  echo "[start_local] Running app in foreground at http://localhost:${PORT:-8000}"
  exec python app.py
fi

mkdir -p .run
if [[ -f .run/app_local.pid ]] && kill -0 "$(cat .run/app_local.pid)" >/dev/null 2>&1; then
  echo "[start_local] App already running with PID $(cat .run/app_local.pid)"
  exit 0
fi

echo "[start_local] Launching app in background"
nohup python app.py > .run/app_local.log 2>&1 &
echo $! > .run/app_local.pid

sleep 2
if kill -0 "$(cat .run/app_local.pid)" >/dev/null 2>&1; then
  echo "[start_local] Stack is up. Dashboard: http://localhost:${PORT:-8000}"
  echo "[start_local] Use scripts/stop_local.sh to stop."
else
  echo "[start_local] ERROR: app failed to start. Check .run/app_local.log" >&2
  exit 1
fi
