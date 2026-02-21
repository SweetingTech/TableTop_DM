# Tabletop DM - Headless Multi-Agent AI-Driven VTT Engine

## Overview
Production-oriented, headless VTT + RPG engine with deterministic state, append-only event ledger, strict visibility filtering, and multi-agent LLM layer (DM, NPCs, Gods, Factions) that can only propose schema-validated actions.

## Current State
- PostgreSQL database with `state`, `ledger`, and `infra_meta` schemas
- 26 database tables across state management, append-only event ledger, and metadata tracking
- 3 SQL migrations applied with checksum tracking
- Demo campaign "Eclipse Keep" seeded with sample entities, encounters, and combat data
- Flask web dashboard on port 5000 for viewing database state

## Project Architecture
- `app.py` - Flask web dashboard (port 5000)
- `templates/` - Jinja2 HTML templates
- `infra/sql/migrations/` - SQL migration files (source of truth for schema)
- `infra/sql/seed/` - Demo seed data
- `infra/sql/init/` - Docker init scripts (for reference only, migrations take precedence)
- `docs/` - Architectural documentation and specs
- `services/` - Backend services (planned, not yet implemented)
- `frontend/` - Frontend application (planned, not yet implemented)

## Database
- Uses Replit's built-in PostgreSQL
- Schemas: `state` (world truth), `ledger` (append-only events), `infra_meta` (migration tracking)
- RLS policies on ledger tables for visibility enforcement
- Migration tracking via `infra_meta.schema_migrations` with SHA-256 checksums

## Running
- `python app.py` starts the Flask dashboard on port 5000

## Recent Changes
- 2026-02-21: Initial Replit setup - database migrations, seed data, Flask dashboard
