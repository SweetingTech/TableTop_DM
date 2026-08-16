#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created .env from .env.example"
fi

COMPOSE_FILE="infra/docker-compose.yml"

qdrant_ready() {
  curl -fsS "http://localhost:${QDRANT_HTTP_PORT:-6333}/healthz" >/dev/null
}

echo "Starting dependency stack..."
docker compose -f "$COMPOSE_FILE" up -d

echo "Waiting for healthy containers..."
for i in {1..60}; do
  if docker inspect -f '{{.State.Health.Status}}' tabletop_postgres 2>/dev/null | grep -q healthy \
    && docker inspect -f '{{.State.Health.Status}}' tabletop_redis 2>/dev/null | grep -q healthy \
    && qdrant_ready; then
    break
  fi
  sleep 2
done

if ! docker inspect -f '{{.State.Health.Status}}' tabletop_postgres 2>/dev/null | grep -q healthy \
  || ! docker inspect -f '{{.State.Health.Status}}' tabletop_redis 2>/dev/null | grep -q healthy \
  || ! qdrant_ready; then
  echo "Error: One or more dependencies did not become ready within the expected time." >&2
  exit 1
fi

echo "Postgres check..."
docker compose -f "$COMPOSE_FILE" exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "Redis check..."
docker compose -f "$COMPOSE_FILE" exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" ping'

echo "Qdrant check..."
curl -fsS "http://localhost:${QDRANT_HTTP_PORT:-6333}/healthz" >/dev/null

echo "OK"
