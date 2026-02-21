#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker CLI is required but was not found in PATH." >&2
  exit 1
fi

echo "[1/5] Starting infrastructure..."
./infra/scripts/phase1_up.sh

echo "[2/5] Running dependency health checks..."
./infra/scripts/phase1_healthcheck.sh

echo "[3/5] Applying schema migrations..."
./infra/scripts/migrate.sh

echo "[4/5] Seeding demo campaign data..."
./infra/scripts/seed_demo.sh

echo "[5/5] Verifying schemas and RLS..."
./infra/scripts/phase2_verify_schema.sh

echo "Setup complete: Phases 1-4 infrastructure, migrations, and demo seed are ready."
