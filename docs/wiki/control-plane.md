# Control Plane

The Control Plane (`/control`) is the management interface for campaigns, sessions, characters, and AI settings.

## Interface Layout

The Control Plane has a tabbed interface:

| Tab | Purpose |
|-----|---------|
| **Campaigns** | Create/manage campaigns |
| **Sessions** | Session lifecycle, archives |
| **Characters** | Character creation and management |
| **RAG** | Document upload and retrieval |
| **AI Settings** | LLM provider configuration |

## Campaigns Tab

### Creating a Campaign

1. Enter a campaign name
2. Click **Create Campaign**

### Campaign Actions

| Action | Description |
|--------|-------------|
| **Select** | Set as active campaign |
| **Edit** | Change campaign name |
| **Archive** | Soft delete (can restore) |
| **Purge** | Permanent deletion |

## Sessions Tab

### Session List

Shows all sessions for the selected campaign:

- **Status badge**: ACTIVE, PAUSED, ENDED
- **Created date**: When session started

### Session Actions

| Button | Action |
|--------|--------|
| **Select** | Set as active session for party management |
| **Pause** | Pause the session |
| **Resume** | Resume a paused session |
| **End** | End the session |

### Creating a Session

Click **Create Session** to start a new session:

- Previous ACTIVE session is automatically ended
- New story state is created
- Chat history starts fresh

### Session Archives

Below the session list, you'll see **Session Archives**:

- Shows sessions that were deleted or completed
- Click **View History** to see:
  - Session metadata
  - Final story state
  - Complete chat history
- Click **Delete** to permanently remove an archive

## Characters Tab

### Quick Character Creation

1. Enter a character concept (e.g., "elven ranger with dark past")
2. Click **AI Generate**
3. Review and edit the generated character
4. Click **Create Character**

### Character Builder Form

Manually create characters with detailed attributes:

**Identity Section**
- Name, Entity Type (PC/NPC), Controlled By

**Attributes Section**
- STR, DEX, CON, INT, WIS, CHA
- Click **Randomize** for 4d6-drop-lowest stats

**Combat Section**
- HP, Armor Class, Speed, Initiative

**Abilities Section**
- Skills, Languages, Class Abilities, Actions

**Equipment Section**
- Weapons, Armor, Equipment, Gold

**Personality Section**
- Traits, Ideals, Bonds, Flaws, Goals

**Background Section**
- Backstory, Allies, Enemies

### Character List

Toggle between **List** and **Cards** view:

- **List**: Compact table view
- **Cards**: Visual cards with portraits

### Character Actions

| Action | Description |
|--------|-------------|
| **Edit** | Open edit modal |
| **Toggle AI** | Switch between HUMAN/AI control |
| **Delete** | Soft delete (can restore) |
| **Restore** | Restore deleted character |

### Session Party Panel

Shows characters in the current session:

- **HP bars** with color coding (green/yellow/red)
- **Status badges**: ACTIVE, DEAD
- **Party Actions**:
  - **Mark Dead**: Record character death
  - **Revive**: Bring back dead character
  - **Remove**: Remove from session

### Adding Characters to Session

1. Select a session from the Sessions tab
2. Use the **Add Character** dropdown
3. Click **Add to Session**

Note: Dead characters (in campaign history) cannot be added unless revived.

## RAG Tab

Upload documents for AI context:

### Uploading Documents

1. Click **Choose File**
2. Select a PDF, TXT, or MD file
3. Click **Upload**
4. Wait for processing (status shows QUEUED → INDEXED)

### Document Actions

| Action | Description |
|--------|-------------|
| **Enable/Disable** | Toggle inclusion in AI context |
| **Reindex** | Reprocess the document |

### Query Testing

1. Enter a query in the text box
2. Click **Query**
3. View retrieved chunks and scores

## AI Settings Tab

Configure the LLM provider for AI features:

### Provider Options

| Provider | Description |
|----------|-------------|
| **Mock** | Deterministic responses (testing) |
| **OpenAI** | OpenAI API (requires key) |
| **Ollama** | Local Ollama server |
| **LM Studio** | Local LM Studio |

### Configuration

| Setting | Description |
|---------|-------------|
| **Base URL** | API endpoint (auto-filled for Ollama/LM Studio) |
| **DM Model** | Model for DM narration |
| **NPC Model** | Model for NPC dialogue |
| **Embedding Model** | Model for RAG embeddings |

### Testing

1. Click **List Models** to see available models
2. Click **Test Provider** to verify connection
3. Click **Save** to store settings

## Tips

- **Campaign Selector**: Use the dropdown in the header to quickly switch campaigns
- **Persistence**: Settings are saved to your browser's local storage
- **Errors**: Check the red error bar at the top for issues
