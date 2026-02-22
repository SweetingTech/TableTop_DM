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

# Safer parsing of .env using python-dotenv or manual parsing if unavailable
# Since requirements-dev.txt is not guaranteed installed yet, we use a simple python parser
# to extract DATABASE_URL and PORT without sourcing.
eval $(python3 -c "
import os
try:
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k, v = line.split('=', 1)
                # primitive unquote
                v = v.strip('\"\'')
                if k in ['DATABASE_URL', 'PORT', 'RUN_FOREGROUND']:
                   print(f'export {k}=\"{v}\"')
except Exception:
    pass
")

export PYTHONUNBUFFERED=1
export PORT="${PORT:-8000}"

echo "[start_local] Checking DATABASE_URL..."
if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[start_local] ERROR: DATABASE_URL is not set." >&2
    exit 1
fi

# Install dependencies if needed
echo "[start_local] Ensuring dependencies..."
if ! python -m pip install -r requirements-dev.txt >/dev/null 2>&1; then
    echo "[start_local] WARNING: Failed to install requirements-dev.txt. Assuming already installed or handled externally."
fi

# Check pyproject.toml dependencies (requires python 3.11+ for tomllib)
python - <<'PY'
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
    data = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    deps = data.get('project', {}).get('dependencies', [])
    if deps:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except ImportError:
    print("Warning: tomllib not found (python < 3.11?), skipping pyproject.toml dependency check.")
except Exception as e:
    print(f"Warning: could not install deps from pyproject.toml: {e}")
PY

echo "[start_local] Running migrations..."
if ! python infra/migrate.py; then
    # Security fix: Do NOT print DATABASE_URL in error message
    echo "[start_local] ERROR: Migrations failed. Check your Postgres connection configuration." >&2
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

echo "[start_local] Waiting for app to be healthy..."
HEALTH_URL="http://localhost:${PORT:-8000}/api/health"
MAX_RETRIES=30
for ((i=1; i<=MAX_RETRIES; i++)); do
    if curl -s -f "$HEALTH_URL" >/dev/null; then
        echo "[start_local] Stack is up. Dashboard: http://localhost:${PORT:-8000}"
        echo "[start_local] Use scripts/stop_local.sh to stop."
        exit 0
    fi
    sleep 1
done

echo "[start_local] ERROR: app failed to start within timeout. Check .run/app_local.log" >&2
# Cleanup
kill "$(cat .run/app_local.pid)" 2>/dev/null || true
rm -f .run/app_local.pid
exit 1
