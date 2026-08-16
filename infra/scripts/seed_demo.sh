#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/infra/docker-compose.yml")

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created .env from .env.example"
fi

set -a
source "$ROOT_DIR/.env"
set +a

wait_for_postgres() {
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "Postgres did not become ready before demo seed." >&2
  "${COMPOSE[@]}" ps postgres >&2 || true
  return 1
}

wait_for_postgres

SEED_FILE="$ROOT_DIR/infra/sql/seed/001_demo_campaign.sql"

echo "Applying demo seed: $(basename "$SEED_FILE")"
"${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SEED_FILE"

echo ""
echo "Demo scenario IDs"
echo "-----------------"
"${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT * FROM (
  SELECT 'campaign_id' AS key, id::text AS value FROM state.campaigns WHERE id = '11111111-1111-1111-1111-111111111111'
  UNION ALL
  SELECT 'session_id', '66666666-6666-6666-6666-666666666661'
  UNION ALL
  SELECT 'encounter_id', id::text FROM state.encounters WHERE id = '55555555-5555-5555-5555-555555555551'
  UNION ALL
  SELECT 'map_id', id::text FROM state.maps WHERE id = '44444444-4444-4444-4444-444444444441'
) t
ORDER BY CASE key WHEN 'campaign_id' THEN 1 WHEN 'session_id' THEN 2 WHEN 'encounter_id' THEN 3 WHEN 'map_id' THEN 4 ELSE 5 END;"

echo ""
echo "Principals"
"${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
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
"${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
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

TOKENS_FILE="$ROOT_DIR/.run/smoke_join_tokens.txt"
mkdir -p "$ROOT_DIR/.run"
cat > "$TOKENS_FILE" <<EOF
DM=dm-smoke-join-22222222-2222-2222-2222-222222222221
PLAYER=player-smoke-join-22222222-2222-2222-2222-222222222222
EOF
echo "Smoke join tokens written to $TOKENS_FILE"
