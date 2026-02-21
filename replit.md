# Tabletop DM - Headless Multi-Agent AI-Driven VTT Engine

## Overview
Production-oriented, headless VTT + RPG engine with deterministic state, append-only event ledger, strict visibility filtering, and multi-agent LLM layer (DM, NPCs, Gods, Factions) that can only propose schema-validated actions.

## Current State
- PostgreSQL database with `state`, `ledger`, and `infra_meta` schemas (26 tables)
- 3 SQL migrations applied with checksum tracking
- Demo campaign "Eclipse Keep" seeded with sample entities, encounters, and combat data
- Flask web dashboard + game console frontend on port 5000
- Full mechanics engine (dice, HP, conditions, attacks, saves)
- Spatial engine (A* pathfinding, line-of-sight, movement validation)
- Orchestrator pipeline (validation, auth, tool execution, ledger append)
- LLM integration via Replit AI Integrations (DM narration, NPC dialogue)
- 9 domain systems: Karma Router, Divine System, NPC Persistence, Consequence Engine, Social System, Faction System, Economy/Property, Content Rating Gate, Map System
- Export/Replay engine for session logs
- WebSocket real-time event streaming
- 14 passing unit tests

## Project Architecture
- `app.py` - Flask + SocketIO web server (port 5000), REST API + WebSocket
- `templates/` - Jinja2 HTML templates (index.html for dashboard, game.html for game console)
- `static/` - Frontend assets (CSS + JS for game console)
- `shared/` - Common infrastructure
  - `shared/db/connection.py` - Database connection layer
  - `shared/schemas/` - Pydantic models (enums, events, contracts)
  - `shared/auth/principal.py` - Principal authentication context
- `services/` - Backend service modules
  - `services/mechanics/` - Deterministic mechanics engine (dice, HP, attacks, saves)
  - `services/spatial/` - Spatial engine (A* pathfinding, LoS, movement)
  - `services/orchestrator/` - Pipeline + state machine
  - `services/ledger/` - Append-only event ledger writer
  - `services/visibility/` - Visibility filtering (RLS-based)
  - `services/llm/` - LLM adapter (OpenAI via Replit integrations)
  - `services/conversations/` - Conversation manager (proximity chat, gods chat)
  - `services/domain/karma/` - Karma router (domain tag → standing updates)
  - `services/domain/divine/` - Divine AP, authority, grudge systems
  - `services/domain/npc/` - NPC persistence + consequence engine
  - `services/domain/social/` - Social system + ambush pipeline
  - `services/domain/factions/` - Faction system (membership, wars, tenets)
  - `services/domain/economy/` - Economy (pricing, property, upkeep)
  - `services/domain/content_rating/` - Content rating gate (SAFE/MATURE/EXPLICIT)
  - `services/domain/maps/` - Map system + procedural generation
  - `services/export/` - Session export (Markdown) + replay engine
- `tests/` - Unit tests
- `infra/sql/` - SQL migrations and seed data
- `docs/` - Architectural documentation and specs

## Database
- Uses Replit's built-in PostgreSQL
- Schemas: `state` (world truth), `ledger` (append-only events), `infra_meta` (migration tracking)
- RLS policies on ledger tables for visibility enforcement
- Migration tracking via `infra_meta.schema_migrations` with SHA-256 checksums

## API Endpoints
- `GET /` - Dashboard (database viewer)
- `GET /game` - Game console frontend
- `GET /api/health` - Health check
- `GET /api/campaigns` - List campaigns
- `GET /api/campaigns/<id>` - Campaign detail
- `GET /api/campaigns/<id>/entities` - Campaign entities
- `GET /api/campaigns/<id>/encounters` - Campaign encounters
- `GET/POST /api/campaigns/<id>/mode` - Get/set game mode
- `GET /api/campaigns/<id>/maps` - Campaign maps
- `GET /api/maps/<id>` - Map detail with nodes
- `POST /api/propose` - Submit intervention proposal
- `POST /api/dice/roll` - Roll dice
- `POST /api/encounters/<id>/advance` - Advance combat turn
- `GET /api/encounters/<id>/slots` - Encounter initiative slots
- `POST /api/chat` - Send chat message
- `POST /api/narrate` - Request AI narration
- `POST /api/content/check` - Content rating check
- `GET /api/export/<session_id>` - Export session to Markdown

## WebSocket Events
- `join_campaign` / `leave_campaign` - Room management
- `submit_intent` - Submit game action via WebSocket
- `game_event` - Broadcast game events
- `turn_advanced` - Turn advancement notifications

## Running
- `python app.py` starts the Flask+SocketIO server on port 5000
- `python tests/test_mechanics.py` runs unit tests

## Recent Changes
- 2026-02-21: Initial Replit setup - database migrations, seed data, Flask dashboard
- 2026-02-21: Built core infrastructure (DB layer, pydantic schemas, auth)
- 2026-02-21: Implemented mechanics engine, spatial engine, orchestrator pipeline
- 2026-02-21: Added LLM integration (DM narration + NPC dialogue agents)
- 2026-02-21: Built 9 domain systems (karma, divine, NPC, social, factions, economy, content rating, maps, export)
- 2026-02-21: Created game console frontend with event feed, command console, map viewer
- 2026-02-21: Added REST API + WebSocket endpoints for full game interaction
