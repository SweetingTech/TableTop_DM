#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f ../.env ]]; then
  cp ../.env.example ../.env
  echo "Created .env from .env.example"
fi

source ../.env

docker compose ps

echo "Checking Postgres connectivity..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT current_database(), now();'

echo "Checking Redis connectivity..."
docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" ping

echo "Checking Qdrant health endpoint..."
curl -fsS "http://localhost:${QDRANT_HTTP_PORT}/healthz"
echo

echo "Phase 1 health checks passed."
