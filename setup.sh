#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker CLI is required but was not found in PATH." >&2
  exit 1
fi

echo "[1/3] Starting infrastructure..."
./infra/scripts/phase1_up.sh

echo "[2/3] Running dependency health checks..."
./infra/scripts/phase1_healthcheck.sh

echo "[3/3] Verifying Phase 2 schemas and RLS..."
./infra/scripts/phase2_verify_schema.sh

echo "Setup complete: Phase 1 and Phase 2 infrastructure are up and verified."
