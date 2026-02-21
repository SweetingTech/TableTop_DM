#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR/infra"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created .env from .env.example"
fi

source "$ROOT_DIR/.env"

SEED_FILE="$ROOT_DIR/infra/sql/seed/001_demo_campaign.sql"

echo "Applying demo seed: $(basename "$SEED_FILE")"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SEED_FILE"

echo ""
echo "Demo scenario IDs"
echo "-----------------"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT 'campaign_id' AS key, id::text AS value FROM state.campaigns WHERE id = '11111111-1111-1111-1111-111111111111'
UNION ALL
SELECT 'session_id', '66666666-6666-6666-6666-666666666661'
UNION ALL
SELECT 'encounter_id', id::text FROM state.encounters WHERE id = '55555555-5555-5555-5555-555555555551'
UNION ALL
SELECT 'map_id', id::text FROM state.maps WHERE id = '44444444-4444-4444-4444-444444444441'
ORDER BY CASE key WHEN 'campaign_id' THEN 1 WHEN 'session_id' THEN 2 WHEN 'encounter_id' THEN 3 WHEN 'map_id' THEN 4 ELSE 5 END;"

echo ""
echo "Principals"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT display_name, id, principal_type
FROM state.principals
WHERE id IN (
  '22222222-2222-2222-2222-222222222221',
  '22222222-2222-2222-2222-222222222222',
  '22222222-2222-2222-2222-222222222223',
  '22222222-2222-2222-2222-222222222224',
  '22222222-2222-2222-2222-222222222225'
)
ORDER BY display_name;"

echo ""
echo "Entities"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT name, id, entity_type
FROM state.entities
WHERE id IN (
  '33333333-3333-3333-3333-333333333331',
  '33333333-3333-3333-3333-333333333332',
  '33333333-3333-3333-3333-333333333333',
  '33333333-3333-3333-3333-333333333334'
)
ORDER BY entity_type, name;"

echo ""
echo "Demo seed complete."
