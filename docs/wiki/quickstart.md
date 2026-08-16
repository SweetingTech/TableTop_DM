# Quick Start Guide

Get TableTop DM running in 5 minutes.

## Prerequisites

- Docker Desktop (recommended) OR
- PostgreSQL, Redis, and Qdrant installed locally
- Python 3.10+
- Git

## Step 1: Clone and Setup

```bash
git clone https://github.com/your-repo/TableTop_DM.git
cd TableTop_DM

# One-time setup (creates .env, starts Docker containers)
./scripts/setup.sh --mode docker
```

## Step 2: Start the Application

```bash
# Docker mode (recommended)
./scripts/start.sh --mode docker

# OR Local mode (if you have services installed)
./scripts/start.sh --mode local
```

## Step 3: Access the Application

Open your browser to:

| Interface | URL | Description |
|-----------|-----|-------------|
| Game Console | http://localhost:8000/game | Play the game |
| Control Plane | http://localhost:8000/control | Manage campaigns |
| Dashboard | http://localhost:8000/ | View database |

## Step 4: Start Playing

1. Open the **Control Plane** at `/control`
2. You'll see the demo campaign "Eclipse Keep" already loaded
3. Click on **Sessions** tab and create a new session (or use existing)
4. Open the **Game Console** at `/game`
5. Start playing! Try these commands:
   - `/help` - Show available commands
   - `/roll 1d20` - Roll a d20
   - Type a message to chat
   - Click on entities to select them
   - Click on the map to move

## Stopping the Application

```bash
./scripts/stop.sh --mode docker
# OR
./scripts/stop.sh --mode local
```

## Next Steps

- [Game Console Guide](game-console.md) - Learn the gameplay interface
- [Character Creation](characters.md) - Create your own characters
- [Control Plane Guide](control-plane.md) - Manage your campaigns
