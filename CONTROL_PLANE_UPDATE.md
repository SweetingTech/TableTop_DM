# Control Plane Update

This update ensures database additions (including new Control Plane tables/migrations) are consistently applied during setup/start flows.

## What changed
- `scripts/setup.sh` (local mode) now performs:
  1. dependency checks (Postgres/Redis/Qdrant)
  2. `infra/scripts/migrate_host.sh`
  3. `infra/scripts/seed_demo_host.sh`

## Why
Previously, local `scripts/setup.sh --mode local` only validated dependencies and did not initialize schema/data. Start paths ran migrations/seeding, but setup did not. This created a gap where Control Plane DB additions might not exist until start was run.

## PowerShell parity
- `scripts/setup.ps1` delegates to `scripts/setup.sh`
- `scripts/start.ps1` delegates to `scripts/start.sh`

So these changes automatically apply to PowerShell flows as well.
