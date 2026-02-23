#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[verify-rc] ERROR: docker compose is required for release-candidate verification." >&2
  exit 1
fi

COMPOSE_FILE="infra/docker-compose.yml"
cleanup() {
  make down || true
}
trap cleanup EXIT

python3 scripts/audit_todo.py --full --strict --mode docker

docker compose -f "$COMPOSE_FILE" config
docker compose -f "$COMPOSE_FILE" build

make up

MAX_HEALTHCHECK_ATTEMPTS="${MAX_HEALTHCHECK_ATTEMPTS:-10}"
HEALTHCHECK_SLEEP_SECONDS="${HEALTHCHECK_SLEEP_SECONDS:-3}"
for attempt in $(seq 1 "$MAX_HEALTHCHECK_ATTEMPTS"); do
  if curl -fsS --max-time 5 http://localhost:8000/readyz >/dev/null; then
    break
  fi

  if [ "$attempt" -eq "$MAX_HEALTHCHECK_ATTEMPTS" ]; then
    echo "[verify-rc] ERROR: service at http://localhost:8000/readyz did not become healthy after $MAX_HEALTHCHECK_ATTEMPTS attempts." >&2
    exit 1
  fi

  sleep "$HEALTHCHECK_SLEEP_SECONDS"
done

make ci
python3 scripts/audit_todo.py --full --strict --mode docker

make down
trap - EXIT

if docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
  echo "[verify-rc] ERROR: orphan containers still running after shutdown." >&2
  exit 1
fi
