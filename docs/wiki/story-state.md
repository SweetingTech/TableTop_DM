# Story State Board

The Story State Board is a DM tracking tool that maintains the narrative context of the current session. It answers the key questions: WHO, WHAT, WHEN, WHERE, WHY, and HOW.

## Overview

The Story State appears in two places:
1. **Game Console** sidebar - Shows location and time
2. **Control Plane** (coming soon) - Full editing interface

## Story State Fields

### WHERE - Location

| Field | Description | Example |
|-------|-------------|---------|
| `current_location` | Current in-game location | "The Rusty Tankard Inn" |
| `location_details` | Additional location info (JSON) | `{"floor": 2, "lighting": "dim"}` |

### WHEN - Time

| Field | Description | Example |
|-------|-------------|---------|
| `game_time` | In-game time/date | "Day 3, Evening" |
| `game_time_details` | Detailed time info (JSON) | `{"year": 1423, "month": "Frost"}` |

### WHO - Participants

| Field | Description | Example |
|-------|-------------|---------|
| `active_npcs` | NPCs in current scene | `[{"name": "Bartender", "disposition": "friendly"}]` |
| `party_status` | Party condition info | `{"morale": "high", "rest_level": "tired"}` |

### WHAT - Objectives

| Field | Description | Example |
|-------|-------------|---------|
| `active_quests` | Current quest objectives | `[{"name": "Find the artifact", "status": "in_progress"}]` |
| `recent_events` | Recent story events | `[{"description": "Met the mysterious stranger", "importance": "high"}]` |

### WHY - Motivations

| Field | Description | Example |
|-------|-------------|---------|
| `plot_threads` | Ongoing story arcs | `[{"name": "The Conspiracy", "status": "developing"}]` |
| `party_goals` | Party's current goals | `[{"goal": "Reach the capital", "priority": "high"}]` |

### HOW - Resources

| Field | Description | Example |
|-------|-------------|---------|
| `key_items` | Important items | `[{"name": "Ancient Key", "description": "Glows faintly"}]` |
| `party_resources` | Party resources | `{"gold": 150, "rations": 5, "torches": 3}` |

### DM Notes

| Field | Description | Visibility |
|-------|-------------|------------|
| `dm_notes` | General DM notes | Visible to all (if shared) |
| `dm_private_notes` | Secret DM notes | DM only |

## Automatic Creation

When a session is created:
1. A story state record is automatically created
2. Initial values are set to defaults
3. `game_time` is set to "Session Start"

## API Endpoints

### Get Story State

```
GET /api/sessions/{session_id}/story_state
```

Returns the current story state for a session.

### Update Story State

```
PUT /api/sessions/{session_id}/story_state
```

Update any story state fields:

```json
{
  "current_location": "The Dark Forest",
  "game_time": "Day 4, Morning",
  "dm_notes": "Party is being followed",
  "change_type": "LOCATION_CHANGE",
  "change_description": "Party entered the forest"
}
```

### Add Story Event

```
POST /api/sessions/{session_id}/story_state/add_event
```

Log a significant event:

```json
{
  "description": "Defeated the goblin chieftain",
  "importance": "high"
}
```

### View Change History

```
GET /api/sessions/{session_id}/story_state/history
```

Returns chronological history of all story state changes.

## Change Types

When updating story state, specify the type of change:

| Type | Description |
|------|-------------|
| `LOCATION_CHANGE` | Party moved to new location |
| `TIME_ADVANCE` | Time progressed |
| `NPC_UPDATE` | NPC added/removed/changed |
| `QUEST_UPDATE` | Quest status changed |
| `EVENT_LOGGED` | Significant event occurred |
| `ITEM_UPDATE` | Key item acquired/lost |
| `RESOURCE_CHANGE` | Party resources changed |
| `NOTE_UPDATE` | DM notes modified |
| `OTHER` | Other changes |

## Best Practices

### For DMs

1. **Update location** when party moves significantly
2. **Advance time** between scenes
3. **Log events** for major story moments
4. **Track NPCs** present in scenes
5. **Use private notes** for secrets

### For Session Continuity

The story state is preserved when:
- Session is paused and resumed
- Session is archived
- Players reconnect

This allows seamless continuation of play across multiple real-world sessions.

## Game Console Display

In the Game Console, the Story State Board shows:
- Current location
- Game time
- Summary (if available)

This helps players stay oriented in the narrative without revealing DM secrets.
