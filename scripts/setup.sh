#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="docker"
INSTALL_DEPS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --install-deps)
      INSTALL_DEPS=1
      shift
      ;;
    *)
      echo "[setup] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p .local-run burn-bag/local-run
[[ -f .env ]] || cp .env.example .env

print_install_help() {
  cat <<'TXT'
Install dependencies:
- macOS (Homebrew): brew install postgresql@16 redis qdrant
- Ubuntu/Debian: sudo apt update && sudo apt install -y postgresql redis-server && (install qdrant from official package/repo)
- Windows (winget): winget install PostgreSQL.PostgreSQL Redis.Redis qdrant.qdrant
- Windows (choco): choco install postgresql redis-64 qdrant
TXT
}

check_port() {
  python - "$1" "$2" <<'PY'
import socket,sys
h,p=sys.argv[1],int(sys.argv[2])
s=socket.socket(); s.settimeout(1.5)
try:
    s.connect((h,p)); sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

if [[ "$MODE" == "docker" ]]; then
  echo "[setup] Running docker setup flow"
  bash ./setup.sh
  exit 0
fi

if [[ "$MODE" != "local" ]]; then
  echo "[setup] Invalid --mode '$MODE' (expected docker|local)" >&2
  exit 1
fi

if [[ "$INSTALL_DEPS" == "1" ]]; then
  echo "[setup] --install-deps requested. Automatic installation is not performed for safety." >&2
fi

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"

missing=0
check_port "$POSTGRES_HOST" "$POSTGRES_PORT" || {
  echo "[setup] Missing dependency: Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}"
  missing=1
}
check_port "$REDIS_HOST" "$REDIS_PORT" || {
  echo "[setup] Missing dependency: Redis at ${REDIS_HOST}:${REDIS_PORT}"
  missing=1
}
check_port "$QDRANT_HOST" "$QDRANT_HTTP_PORT" || {
  echo "[setup] Missing dependency: Qdrant at ${QDRANT_HOST}:${QDRANT_HTTP_PORT}"
  missing=1
}

if [[ "$missing" == "1" ]]; then
  echo "[setup] Local dependency check failed."
  print_install_help
  exit 1
fi

echo "[setup] Local dependency check passed."
echo "[setup] Applying migrations for local mode..."
bash infra/scripts/migrate_host.sh

echo "[setup] Applying demo seed for local mode..."
bash infra/scripts/seed_demo_host.sh

echo "[setup] Local setup complete (dependencies + migrations + seed)."
