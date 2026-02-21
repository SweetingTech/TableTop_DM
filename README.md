# Headless Multi-Agent AI-Driven VTT Engine
Production-oriented, headless VTT + RPG engine with deterministic state, append-only event ledger, strict visibility filtering, and multi-agent LLM layer (DM, NPCs, Gods, Factions) that can only propose schema-validated actions.


## Implementation Status
**All 20 phases complete.** See `todo.md` for the full checklist.

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Repo structure + contracts/specs | Done |
| 1 | Infrastructure (PostgreSQL via Docker Compose or Replit) | Done |
| 2 | Data model + schemas (state, ledger, security) | Done |
| 3 | Event envelope + intervention contracts | Done |
| 4 | Migrations + seed data (Eclipse Keep demo) | Done |
| 5 | Mechanics engine + spatial engine | Done |
| 6 | Orchestrator/router + validation pipeline | Done |
| 7 | Visibility enforcement (RLS) | Done |
| 8 | LLM adapter (DM narration + NPC dialogue) | Done |
| 9 | Conversation pipelines (Olympus, proximity, off-screen) | Done |
| 10 | Karma router + divine standings | Done |
| 11 | Divine system (AP, authority, grudges) | Done |
| 12 | NPC persistence + consequence engine | Done |
| 13 | Social system + ambush pipeline | Done |
| 14 | Guilds/factions/patrons | Done |
| 15 | Economy + property | Done |
| 16 | Content rating gate | Done |
| 17 | Maps (upload + procedural generation) | Done |
| 18 | Frontend MVP (event feed, console, map viewer) | Done |
| 19 | Export + replay + debugging | Done |
| 20 | Observability + CI/testing (23 unit tests) | Done |


## Quickstart

### Option A: Docker Compose (recommended for local development)
```bash
cp .env.example .env        # edit values as needed
docker compose up --build   # starts Postgres + app
```
On first boot the entrypoint automatically:
1. Waits for Postgres to be healthy
2. Runs all SQL migrations (`infra/sql/migrations/`)
3. Seeds the "Eclipse Keep" demo campaign (`infra/sql/seed/`)

Once running:
- **Dashboard:** `http://localhost:5000/`
- **Game Console:** `http://localhost:5000/game`
- **Tests:** `docker compose exec app python tests/test_mechanics.py`

To stop: `docker compose down` (add `-v` to also wipe the database volume).

### Option B: Replit
The project runs on Replit out of the box. The built-in PostgreSQL database is automatically available via `DATABASE_URL`, and migrations/seeds are already applied.
```bash
python app.py
```

### Option C: Manual (no Docker)
Requires Python 3.11+ and a running Postgres instance.
```bash
pip install -r pyproject.toml   # or: uv pip install -r pyproject.toml
export DATABASE_URL=postgresql://user:pass@localhost:5432/tabletop_dm
python infra/migrate.py         # apply migrations
python infra/seed.py            # seed demo data
python app.py                   # start server on port 5000
```

All options provide the same endpoints:
- **Dashboard:** `http://localhost:5000/` — view campaigns, entities, encounters, maps, schema
- **Game Console:** `http://localhost:5000/game` — interactive game interface with event feed, commands, map viewer
- **Tests:** `python tests/test_mechanics.py` — runs 23 unit tests


## Database
Uses PostgreSQL with three schemas (Replit built-in or Docker Compose):
- **`state`** — canonical world truth (campaigns, entities, encounters, maps, factions, economy, etc.)
- **`ledger`** — append-only event log with `visible_to[]` principal filtering
- **`infra_meta`** — migration tracking with SHA-256 checksums

Migrations are in `infra/sql/migrations/`. Seed data for the "Eclipse Keep" demo campaign is in `infra/sql/seed/`.


## Project Structure
```
app.py                              Flask + SocketIO server (port 5000)
templates/
  index.html                        Dashboard template
  game.html                         Game console template
static/
  css/app.css                       Game console styles
  js/app.js                         Game console client
shared/
  db/connection.py                  Database connection layer
  schemas/enums.py                  Enums (GameMode, EventType, TensionLevel, etc.)
  schemas/events.py                 Pydantic event models (EventEnvelope, StateDelta)
  schemas/contracts.py              Intervention proposal contracts
  auth/principal.py                 Principal authentication context
services/
  mechanics/
    dice.py                         Crypto RNG dice roller
    engine.py                       HP, conditions, attacks, saves
  spatial/
    engine.py                       A* pathfinding, line-of-sight, movement validation
  orchestrator/
    pipeline.py                     Validation + auth + tool exec + ledger append
    state_machine.py                Mode + encounter state management
  ledger/
    writer.py                       Append-only ledger writer
  visibility/
    filter.py                       RLS-based visibility filtering
  llm/
    adapter.py                      OpenAI LLM adapter (DM narration, NPC dialogue)
  conversations/
    manager.py                      Proximity chat, gods chat pipelines
  domain/
    karma/router.py                 Domain tag -> standing updates
    divine/system.py                Divine AP, authority ranks, grudges
    npc/persistence.py              NPC instantiation + consequence engine
    social/system.py                Tension ladder + ambush pipeline
    factions/system.py              Faction membership, wars, tenet enforcement
    economy/system.py               Dynamic pricing, property, upkeep
    content_rating/gate.py          SAFE/MATURE/EXPLICIT content filtering
    maps/system.py                  Map management + procedural generation
  export/
    exporter.py                     Session export (Markdown) + replay engine
tests/
  test_mechanics.py                 23 unit tests
infra/sql/                          SQL migrations and seed data
docs/                               Architecture specs
```


## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard (database viewer) |
| GET | `/game` | Game console frontend |
| GET | `/api/health` | Health check |
| GET | `/api/campaigns` | List campaigns |
| GET | `/api/campaigns/<id>` | Campaign detail |
| GET | `/api/campaigns/<id>/entities` | Campaign entities |
| GET | `/api/campaigns/<id>/encounters` | Campaign encounters |
| GET/POST | `/api/campaigns/<id>/mode` | Get/set game mode |
| GET | `/api/campaigns/<id>/maps` | Campaign maps |
| GET | `/api/maps/<id>` | Map detail with nodes |
| POST | `/api/propose` | Submit intervention proposal |
| POST | `/api/dice/roll` | Roll dice |
| POST | `/api/encounters/<id>/advance` | Advance combat turn |
| GET | `/api/encounters/<id>/slots` | Encounter initiative slots |
| POST | `/api/chat` | Send chat message |
| POST | `/api/narrate` | Request AI narration |
| POST | `/api/content/check` | Content rating check |
| GET | `/api/export/<session_id>` | Export session to Markdown |

## WebSocket Events
| Event | Direction | Description |
|-------|-----------|-------------|
| `join_campaign` | Client -> Server | Join campaign room |
| `leave_campaign` | Client -> Server | Leave campaign room |
| `submit_intent` | Client -> Server | Submit game action |
| `game_event` | Server -> Client | Broadcast game events |
| `turn_advanced` | Server -> Client | Turn advancement notification |


## Game Console Commands
| Command | Description |
|---------|-------------|
| `/roll [dice] [modifier]` | Roll dice (e.g., `/roll 2d6 3`) |
| `/mode [MODE]` | Change game mode (EXPLORATION, COMBAT, DIALOGUE, CUTSCENE, DOWNTIME) |
| `/advance` | Advance combat turn |
| `/narrate [context]` | Request AI narration |
| `/help` | Show available commands |


## Prime Directives (Non-Negotiable)
- **LLMs are text engines only.** No dice, no math, no inventory truth, no spatial truth, no direct state mutation. LLM outputs must be schema-validated proposals or narration/dialogue.
- **Deterministic backend is law.** Mechanics, RNG, spatial logic, and state transitions are server-side only.
- **One Path to Reality:** `Proposal -> Schema Validation -> Auth/Resource Check -> Tool Call -> State Delta -> Ledger Event -> Broadcast`
- **Append-only Ledger.** Never updated, only appended. State DB is mutable current truth.
- **Visibility enforced at the data layer.** Every ledger record has `visible_to[]`. Reads and broadcasts are filtered. No exceptions.
- **Idempotent commits.** All proposals use `idempotency_key`. Retries never double-apply deltas.
- **Schema versioning required.** Every event envelope carries `event_version` / `contract_version`.


## Architecture Overview

### Data Pillars
- **State DB (Postgres):** canonical world truth — entities, stats, inventory, coordinates, factions, economy metrics, divine standings, interventions, triggers
- **Ledger DB (Postgres, append-only):** event envelopes, tool calls/results, intents, reactions, deltas, narration/dialogue — every row includes `visible_to[]`

### Backend Services
- **Orchestrator/Router:** mode switching, turn loop, intent windows, reaction stack, validation pipeline, transactional commits, broadcast
- **Mechanics Engine:** deterministic dice, HP/resources, conditions, combat resolution, inventory
- **Spatial Engine:** A* pathfinding, line-of-sight raycasts, threat radius triggers, movement validation
- **LLM Adapter:** OpenAI via Replit AI Integrations — DM narration agent + NPC dialogue agent (structured JSON output)
- **Karma Router:** deterministic scoring from `domain_tags` -> standings -> threshold wake triggers
- **Divine System:** equal AP pools, authority ranks, override rules, grudge tracking
- **Faction Service:** membership, wars, tenet enforcement (spell revocation, curses, bounties)
- **Economy/Property Service:** dynamic pricing via scarcity/stability, property ownership/upkeep/raid risk
- **Content Rating Gate:** SAFE/MATURE/EXPLICIT enforcement at generation and pre-broadcast

### Frontend
- **Game Console:** WebSocket-connected event feed, slash command console, entity sidebar with HP bars, initiative tracker, canvas map viewer with terrain rendering


## Canonical Object Model
- **Principal:** actor/viewer identity (human player, DM agent, god agent, NPC agent). Defines visibility + permissions.
- **Entity:** thing in the world (PC/NPC/monster/object/location/faction/god). Has stats and state.
- **Control handoff:** each entity has `controlled_by` and `controller_principal_id`.

Hierarchy:
- **Campaign:** persistent container
- **Session:** play instance; produces summaries + checkpoints
- **Encounter:** combat instance with initiative + rounds

Mode state machine (GM-controlled):
- `EXPLORATION -> SOCIAL -> COMBAT -> CUTSCENE -> DOWNTIME`
- Combat does NOT auto-trigger; requires explicit mode transition.


## Key Systems

### Social System
Tension ladder: `CALM -> SUSPICIOUS -> HOSTILE -> WEAPONS_DRAWN -> COMBAT`
Ambush pipeline: stealth intent + awareness checks + surprise rules + GM commits combat transition.

### NPC Consequence Engine
Death triggers cascading consequences: investigations, bounties, faction hostility shifts, rumor propagation, economy modifiers, divine tag triggers. Murder-hobo behavior causes systemic fallout without DM manual intervention.

### Content Controls
- SAFE (PG-13), MATURE (fade-to-black), EXPLICIT (adult with consent flags)
- Hard blocks always: minors, non-consensual sexual content
- Enforced at LLM generation and pre-broadcast

### Combat Pre-Registered Triggers
AI entities register deterministic reaction triggers (ON_MOVEMENT, ON_ATTACKED, ON_CAST) executed with zero LLM calls.
