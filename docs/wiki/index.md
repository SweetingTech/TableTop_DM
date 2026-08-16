# TableTop DM - User Guide & Wiki

Welcome to TableTop DM, a headless multi-agent AI-driven Virtual Tabletop (VTT) engine. This wiki serves as both a user guide and the authoritative documentation for the system.

## Quick Navigation

### Getting Started
- [Quick Start Guide](quickstart.md) - Get up and running in 5 minutes
- [1.0 Scope](../release/1.0-scope.md) - Supported release scope and requirements

### User Interfaces
- [Game Console](game-console.md) - The main gameplay interface
- [Control Plane](control-plane.md) - Campaign and character management

### Core Features
- [Campaigns](control-plane.md#campaigns-tab) - Creating and managing campaigns
- [Sessions](sessions.md) - Session lifecycle and management
- [Characters](characters.md) - Character creation and management
- [Combat and Maps](game-console.md) - Combat, initiative, map viewing, and movement

### DM Tools
- [Story State Board](story-state.md) - Tracking who/what/when/where/why/how
- [AI and NPC Behavior](../SPEC_MASTER.md) - Narration and agent behavior contracts
- [Session Archives](sessions.md) - Session lifecycle and history

### Technical Reference
- [API and WebSocket Reference](../../README.md#api-reference) - REST endpoints and real-time events
- [Commands](commands.md) - Console commands reference
- [Configuration](../../README.md#configuration) - Environment variables and settings

---

## Interface Overview

TableTop DM has three main interfaces:

| Interface | URL | Purpose |
|-----------|-----|---------|
| **Game Console** | `/game` | Real-time gameplay with chat, map, and combat |
| **Control Plane** | `/control` | Campaign/session/character management |
| **Dashboard** | `/` | Database viewer and system stats |

## Key Concepts

### Principals
A **Principal** is an actor in the system (human player, DM, AI agent). Each principal has:
- A unique ID
- Display name
- Type (HUMAN, AI_DM, AI_NPC, SYSTEM)
- Permissions based on campaign membership

### Entities
An **Entity** is anything in the game world:
- Player Characters (PCs)
- Non-Player Characters (NPCs)
- Monsters
- Objects
- Locations

### Sessions
A **Session** is a play instance within a campaign:
- Has a status (ACTIVE, PAUSED, ENDED)
- Tracks story state
- Contains chat history
- Can be archived for historical reference

### Encounters
An **Encounter** is a combat instance:
- Has initiative order
- Tracks turns and rounds
- Contains entity slots for participants

---

## Getting Help

- **In-App Help**: Press `?` or type `/help` in the game console
- **GitHub Issues**: Report bugs at the project repository
- **This Wiki**: Browse the documentation for detailed guides

---

*This wiki is the ground truth for TableTop DM. If the application behaves differently than documented here, the documentation should be updated to match the actual behavior.*
