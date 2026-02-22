#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[verify-rc] ERROR: docker compose is required for release-candidate verification." >&2
  exit 1
fi

COMPOSE_FILE="infra/docker-compose.yml"

python3 scripts/audit_todo.py --full --strict

docker compose -f "$COMPOSE_FILE" config
docker compose -f "$COMPOSE_FILE" build

make up
curl -fsS http://localhost:8000/health
make down

if docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
  echo "[verify-rc] ERROR: orphan containers still running after shutdown." >&2
  exit 1
fi

make ci
python3 scripts/audit_todo.py --full --strict
