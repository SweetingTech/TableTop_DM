#!/usr/bin/env bash
set -e

echo "=== Tabletop DM - Docker Entrypoint ==="
echo "Waiting for database..."

until python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.close()
print('Database ready.')
" 2>/dev/null; do
    echo "  Postgres not ready yet, retrying in 2s..."
    sleep 2
done

echo "Running migrations..."
python infra/migrate.py

echo "Seeding demo data (if not already present)..."
python infra/seed.py

echo "=== Starting application ==="
exec "$@"
