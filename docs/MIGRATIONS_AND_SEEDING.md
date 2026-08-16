# MIGRATIONS_AND_SEEDING

## Phase 4 migration toolchain
- Migration SQL files live in `infra/sql/migrations/` and run in lexical order.
- `infra/scripts/migrate.sh` creates/uses `infra_meta.schema_migrations` to track:
  - migration filename (`version`)
  - SHA-256 checksum
  - timestamp applied
- Re-running `make migrate` is safe:
  - already-applied migrations are skipped
  - checksum drift fails fast to prevent silent schema skew
- For disposable Docker development databases, recover from checksum drift by
  rebuilding dependency volumes:
  `.\scripts\start.ps1 -Mode docker -ResetDb` on Windows or
  `./scripts/start.sh --mode docker --reset-db` in Bash. This deletes local
  Postgres, Redis, and Qdrant Docker volume data, then reruns migrations and
  seeds the demo campaign.

## Phase 4 demo seed
- Seed SQL lives at `infra/sql/seed/001_demo_campaign.sql`.
- Apply with `make seed-demo`.
- Script prints campaign/session/encounter/map IDs and table rows for principals/entities.

## Typical sequence
1. `./infra/scripts/phase1_up.sh`
2. `make migrate`
3. `make seed-demo`
4. `./infra/scripts/phase2_verify_schema.sh`

## Local Mode (No Docker)
- For local mode, use `python infra/migrate.py` and `python infra/seed.py`.
- These are wrapped by `make local-up` (which runs migrations and seeds automatically).
- Requires `DATABASE_URL` in `.env` to point to a running Postgres instance.
