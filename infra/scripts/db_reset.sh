#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="infra/docker-compose.yml"

echo "Stopping and deleting volumes..."
docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans

echo "Starting fresh..."
docker compose -f "$COMPOSE_FILE" up -d
