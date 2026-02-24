# Sessions

A Session represents a single play instance within a campaign. Sessions track gameplay progress, chat history, and story state.

## Session Lifecycle

```
┌─────────┐     Create      ┌─────────┐
│  None   │ ───────────────→│ ACTIVE  │
└─────────┘                  └────┬────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
              ┌─────────┐   ┌─────────┐   ┌─────────┐
              │ PAUSED  │   │  ENDED  │   │ARCHIVED │
              └────┬────┘   └─────────┘   └─────────┘
                   │             ▲
                   └─────────────┘
                      Resume
```

## Session Statuses

| Status | Description |
|--------|-------------|
| **ACTIVE** | Currently in use for gameplay |
| **PAUSED** | Temporarily suspended |
| **ENDED** | Completed, no longer active |

## Creating a Session

### Via Control Plane

1. Go to `/control`
2. Select a campaign
3. Click **Sessions** tab
4. Click **Create Session**

### Via API

```
POST /api/campaigns/{campaign_id}/sessions
```

### What Happens on Creation

1. Any existing ACTIVE session is automatically ENDED
2. New session is created with ACTIVE status
3. Story state record is automatically created
4. Chat history starts fresh

## Session Actions

### Pause

Temporarily suspend a session:
- Players can reconnect later
- Story state is preserved
- Chat history is preserved

```
POST /api/sessions/{session_id}/pause
```

### Resume

Continue a paused session:
- Changes status to ACTIVE
- Players can rejoin

```
POST /api/sessions/{session_id}/resume
```

### End

Complete a session:
- Marks session as ENDED
- Session cannot be resumed
- Data is preserved for reference

```
POST /api/sessions/{session_id}/end
```

## Session Resume Data

When returning to a session, the system provides:

1. **Session metadata** - ID, status, timestamps
2. **Story state** - Current location, time, notes
3. **Chat history** - Recent messages (last 50)
4. **Party info** - Characters in session

### API Endpoint

```
GET /api/sessions/{session_id}/resume_data
```

Response:
```json
{
  "session": {
    "id": "...",
    "status": "ACTIVE",
    "campaign_id": "...",
    "started_at": "2024-01-15T10:00:00Z"
  },
  "story_state": {
    "current_location": "The Tavern",
    "game_time": "Evening",
    "dm_notes": "..."
  },
  "chat_history": [
    {"event_type": "CHAT", "payload": {...}, "created_at": "..."}
  ],
  "party": [
    {"entity_id": "...", "name": "Thorin", "status": "ACTIVE"}
  ]
}
```

## Chat History

### Viewing Chat History

```
GET /api/sessions/{session_id}/chat_history?limit=100
```

Parameters:
- `limit` - Number of messages (default: 100)
- `before_seq` - Pagination cursor

### Chat Message Types

| Type | Description |
|------|-------------|
| `CHAT` | Player/NPC dialogue |
| `ACTION` | Game actions and results |
| `NARRATION` | DM/AI narration |
| `SYSTEM` | System messages |
| `GM_WHISPER` | Private DM messages |

## Session Archives

When a session is deleted, it's automatically archived:

1. Chat history is preserved in JSON
2. Final story state is captured
3. Archive record is created

### Viewing Archives

```
GET /api/campaigns/{campaign_id}/session_archives
```

### Archive Contents

| Field | Description |
|-------|-------------|
| `original_session_id` | Original session UUID |
| `session_name` | Display name (if set) |
| `started_at` / `ended_at` | Session timestamps |
| `chat_history` | Complete chat log (JSON) |
| `final_story_state` | Story state at archive time |
| `session_summary` | Optional summary text |
| `archive_reason` | COMPLETED, DELETED, ABANDONED, MERGED |

### Manual Archive

Archive a session without deleting:

```
POST /api/sessions/{session_id}/archive
```

Body:
```json
{
  "summary": "Party defeated the dragon",
  "reason": "COMPLETED"
}
```

### Deleting Archives

Permanently remove an archive:

```
DELETE /api/session_archives/{archive_id}
```

**Warning**: This cannot be undone!

## Session Characters

Characters can be assigned to sessions:

### Adding Characters

```
POST /api/sessions/{session_id}/characters
```

Body:
```json
{
  "entity_id": "character-uuid"
}
```

### Character Status in Session

| Status | Description |
|--------|-------------|
| `ACTIVE` | Currently participating |
| `DEAD` | Died during session |
| `REMOVED` | Manually removed |
| `RETIRED` | Character retired |

### Death Tracking

When a character dies:
1. Mark as DEAD in session
2. Record death details
3. Prevent rejoining unless revived

### Reviving Characters

```
POST /api/sessions/{session_id}/characters/{entity_id}/revive
```

Body:
```json
{
  "revive_method": "Resurrection spell",
  "revive_details": {"caster": "Cleric"}
}
```

## Best Practices

1. **One Active Session** - Only one session should be ACTIVE at a time
2. **Pause for Breaks** - Use PAUSE for short breaks
3. **End Completed Sessions** - End sessions when story arc completes
4. **Archive Important Sessions** - Keep archives of memorable games
5. **Add Summaries** - Write summaries for archived sessions
