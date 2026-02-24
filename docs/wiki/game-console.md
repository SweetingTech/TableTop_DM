# Game Console

The Game Console (`/game`) is the main gameplay interface where you interact with the game world.

## Interface Layout

```
+--------------------------------------------------+
|  TABLETOP DM  |  Control Plane  |  Campaign Name |
+--------------------------------------------------+
|  Story State  |                    |  Entity     |
|  - Location   |   Event Feed /     |  Detail     |
|  - Time       |   Map View         |             |
+---------------+                    +-------------+
|  Entities     |                    |  Encounter  |
|  - Player 1   |   [Tabs]           |  Select     |
|  - NPC 1      |   Feed | Map       +-------------+
|  - Monster 1  |                    |  Initiative |
+---------------+--------------------+  Tracker    |
|  Command Input: /help              +-------------+
+------------------------------------+  Quick      |
                                     |  Actions    |
                                     +-------------+
```

## Story State Board (Left Sidebar)

The Story State Board shows the current narrative context:

| Field | Description |
|-------|-------------|
| **Location** | Current in-game location |
| **Time** | In-game time/date |

The DM updates these values through the Control Plane to help players track the narrative.

## Event Feed (Center)

The Event Feed shows all game events in real-time:

- **Chat messages** - Player and NPC dialogue
- **Actions** - Combat rolls, movement, abilities
- **Narration** - AI-generated descriptions
- **System messages** - Turn changes, mode switches

### Event Types (Color Coded)

| Color | Type | Example |
|-------|------|---------|
| Blue | Chat/Dialogue | "Hello, traveler!" |
| Purple | Narration | *The goblin lunges forward...* |
| Orange | Tool/Action | Attack Roll: 1d20+5 = 18 |
| Yellow | System | Turn advanced |
| Red | Error | Target not found |

## Map View (Center Tab)

Click the **Map** tab to see the tactical map:

- **Click to Move**: Select an entity, then click a tile to move
- **Token Colors**: Different colors for PCs, NPCs, and monsters
- **Walls**: Gray tiles are impassable
- **Pathfinding**: Movement is validated by the server

## Entity List (Left Sidebar)

Shows all entities in the current scene:

- Click to **select** an entity
- **Green border** = You control this entity
- **HP bars** show current health
- Entity types: PC, NPC, MONSTER

## Entity Detail (Right Panel)

When you select an entity, shows:

- Name and type
- HP (current/max)
- Armor Class
- Stats and abilities

## Initiative Tracker (Right Panel)

During combat:

- Shows turn order
- **Highlighted** = Current turn
- Shows each entity's initiative value

## Quick Actions (Right Panel)

| Button | Action |
|--------|--------|
| **Roll d20** | Quick d20 roll |
| **Attack Target** | Attack selected target |
| **End Turn** | End your current turn |
| **Advance Initiative** | Move to next turn (DM) |
| **AI Narration** | Request AI narration |

## Console Commands

Type in the command input at the bottom:

| Command | Description | Example |
|---------|-------------|---------|
| `/help` | Show all commands | `/help` |
| `/roll [dice] [mod]` | Roll dice | `/roll 2d6 3` |
| `/attack [target]` | Attack a target | `/attack Goblin` |
| `/endturn` | End your turn | `/endturn` |
| `/mode [MODE]` | Change game mode | `/mode COMBAT` |
| `/say @target msg` | Speak to NPC | `/say @Innkeeper Hello` |
| `/advance` | Advance initiative | `/advance` |
| `/narrate [context]` | AI narration | `/narrate battle` |

## Chat

Type any message without a `/` prefix to chat as your character.

Your message is sent to the session and visible to all players and NPCs in audible range.

## Session Resume

When you return to a session, the console automatically:

1. Loads the session's story state
2. Displays recent chat history
3. Shows "Session resumed" message

This allows seamless continuation of play.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send command/message |
| `?` | Show help |

## Connection Status

- **Green dot** (top right) = Connected via WebSocket
- **Red dot** = Disconnected (will auto-reconnect)

Events are broadcast in real-time when connected.
