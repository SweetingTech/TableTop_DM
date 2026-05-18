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
      echo "[start] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$MODE" != "docker" && "$MODE" != "local" ]]; then
  echo "[start] Invalid --mode '$MODE' (expected docker|local)" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] Created .env from .env.example"
fi

load_env_file() {
  python - <<'PY'
from pathlib import Path

p = Path('.env')
if p.exists():
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        print(f'export {k.strip()}={v.strip()}')
PY
}

# Load .env into current shell so app.py sees DATABASE_URL and dependency host/port vars.
eval "$(load_env_file)"

mkdir -p burn-bag/local-run .local-run
APP_PID_FILE=".local-run/app.pid"
APP_LOG_FILE="burn-bag/local-run/app.log"
DEPS_PROVIDER_FILE=".local-run/deps-provider"
DEPS_STARTED_FILE=".local-run/deps-started-by-start"

ensure_python_deps() {
  python -m pip install -r requirements-dev.txt >/dev/null
  python - <<'PY'
import subprocess
import tomllib
from pathlib import Path

data = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
deps = data.get('project', {}).get('dependencies', [])
if deps:
    subprocess.check_call(['python', '-m', 'pip', 'install', *deps], stdout=subprocess.DEVNULL)
PY
}

wait_ready() {
  local url="${VTT_READY_URL:-http://localhost:${PORT:-8000}/readyz}"
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 "$url" >/dev/null; then
      echo "[start] Ready at $url"
      return 0
    fi
    sleep 2
  done
  echo "[start] ERROR: readiness check failed at $url" >&2
  return 1
}

start_host_app() {
  export PYTHONUNBUFFERED=1
  export PORT="${PORT:-8000}"
  export TTDM_DEBUG="${TTDM_DEBUG:-0}"
  if [[ -f "$APP_PID_FILE" ]] && kill -0 "$(cat "$APP_PID_FILE")" >/dev/null 2>&1; then
    echo "[start] App already running with PID $(cat "$APP_PID_FILE")"
    return 0
  fi
  nohup python app.py > "$APP_LOG_FILE" 2>&1 &
  echo $! > "$APP_PID_FILE"
}

docker_runtime_available() {
  bash scripts/docker_runtime_available.sh
}

start_deps_docker() {
  if ! docker_runtime_available; then
    echo "[start] ERROR: docker runtime is unavailable for docker dependency provider" >&2
    return 1
  fi
  local compose=(docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/infra/docker-compose.yml")
  "${compose[@]}" up -d postgres redis qdrant
  for _ in $(seq 1 40); do
    if "${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
  echo docker > "$DEPS_PROVIDER_FILE"
  echo "1" > "$DEPS_STARTED_FILE"
}

check_host_dep() {
  local host="$1"; local port="$2"; local name="$3"
  python - "$host" "$port" "$name" <<'PY'
import socket,sys
h,p,n=sys.argv[1],int(sys.argv[2]),sys.argv[3]
s=socket.socket(); s.settimeout(1.5)
try:
    s.connect((h,p))
    print(f"ok:{n}")
except Exception:
    print(f"fail:{n}")
    sys.exit(1)
finally:
    s.close()
PY
}

run_migrate_seed_and_app() {
  local migrate_cmd="$1"
  local seed_cmd="$2"
  bash "$migrate_cmd"
  bash "$seed_cmd"
  ensure_python_deps
  start_host_app
  wait_ready
}

start_local_mode() {
  local provider="${DEPS_PROVIDER:-auto}"
  if [[ "$provider" == "auto" ]]; then
    if docker_runtime_available; then
      provider="docker"
    else
      provider="host"
    fi
  fi

  if [[ "$provider" == "docker" ]]; then
    start_deps_docker
    run_migrate_seed_and_app "infra/scripts/migrate.sh" "infra/scripts/seed_demo.sh"
  elif [[ "$provider" == "host" ]]; then
    check_host_dep "${POSTGRES_HOST:-localhost}" "${POSTGRES_PORT:-5432}" "postgres" || {
      echo "[start] Host Postgres unavailable. Run: ./scripts/setup.sh --mode local" >&2
      return 1
    }
    check_host_dep "${REDIS_HOST:-localhost}" "${REDIS_PORT:-6379}" "redis" || {
      echo "[start] Host Redis unavailable. Run: ./scripts/setup.sh --mode local" >&2
      return 1
    }
    check_host_dep "${QDRANT_HOST:-localhost}" "${QDRANT_HTTP_PORT:-6333}" "qdrant" || {
      echo "[start] Host Qdrant unavailable. Run: ./scripts/setup.sh --mode local" >&2
      return 1
    }
    echo host > "$DEPS_PROVIDER_FILE"
    rm -f "$DEPS_STARTED_FILE"
    run_migrate_seed_and_app "infra/scripts/migrate_host.sh" "infra/scripts/seed_demo_host.sh"
  else
    echo "[start] ERROR: DEPS_PROVIDER must be auto|docker|host" >&2
    return 1
  fi
}

start_docker_mode() {
  start_deps_docker
  run_migrate_seed_and_app "infra/scripts/migrate.sh" "infra/scripts/seed_demo.sh"
}

if [[ "$MODE" == "docker" ]]; then
  start_docker_mode
else
  start_local_mode
fi

echo "[start] Started in $MODE mode"
