#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR/infra"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created .env from .env.example"
fi

set -a
source "$ROOT_DIR/.env"
set +a

if ! docker compose ps postgres >/dev/null 2>&1; then
  echo "Postgres service not found in compose. Run ./infra/scripts/phase1_up.sh first." >&2
  exit 1
fi

SQL_BOOTSTRAP=$(cat <<'SQL'
CREATE SCHEMA IF NOT EXISTS infra_meta;
CREATE TABLE IF NOT EXISTS infra_meta.schema_migrations (
  version text PRIMARY KEY,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL
)

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$SQL_BOOTSTRAP"

for migration in "$ROOT_DIR"/infra/sql/migrations/*.sql; do
  [[ -e "$migration" ]] || continue

  version="$(basename "$migration")"
  if [[ ! "$version" =~ ^[0-9]{3}_[a-z_]+\.sql$ ]]; then
    echo "Skipping migration with unsafe filename: $version" >&2
    continue
  fi
  checksum="$(sha256sum "$migration" | cut -d ' ' -f 1)"

  applied_checksum=$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT checksum FROM infra_meta.schema_migrations WHERE version = '$version';")

  if [[ -n "$applied_checksum" ]]; then
    if [[ "$applied_checksum" != "$checksum" ]]; then
      echo "Checksum mismatch for already-applied migration $version" >&2
      exit 1
    fi
    echo "Skipping $version (already applied)"
    continue
  fi

  echo "Applying $version"
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$migration"

  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "INSERT INTO infra_meta.schema_migrations(version, checksum) VALUES ('$version', '$checksum');"
done

echo "Migrations complete."
