#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f ../.env ]]; then
  cp ../.env.example ../.env
  echo "Created .env from .env.example"
fi

source ../.env

read -r -d '' SQL <<'EOSQL' || true
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('state','ledger')
ORDER BY table_schema, table_name;
EOSQL

docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$SQL"

echo ""
echo "Verifying RLS enabled on ledger tables..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT schemaname, tablename, rowsecurity FROM pg_tables WHERE schemaname='ledger' ORDER BY tablename;"

echo ""
echo "Phase 2 schema verification complete."
