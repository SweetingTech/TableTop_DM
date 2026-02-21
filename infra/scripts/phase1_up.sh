#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f ../.env ]]; then
  cp ../.env.example ../.env
  echo "Created .env from .env.example"
fi

docker compose up -d

echo "Services started. Run ./infra/scripts/phase1_healthcheck.sh to verify readiness."
