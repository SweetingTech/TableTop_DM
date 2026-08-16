# Console Commands Reference

All commands start with `/` and are entered in the Game Console command input.

## General Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/help` | Show all available commands | `/help` |

## Dice Rolling

| Command | Description | Example |
|---------|-------------|---------|
| `/roll [dice] [modifier]` | Roll dice with optional modifier | `/roll 2d6 3` |
| `/roll` | Roll 1d20 (default) | `/roll` |

**Dice format**: `NdS` where N = number of dice, S = sides
- `1d20` - One 20-sided die
- `2d6` - Two 6-sided dice
- `4d6` - Four 6-sided dice

**Modifiers**: Add or subtract from total
- `/roll 1d20 5` = 1d20 + 5
- `/roll 1d20 -2` = 1d20 - 2

## Combat Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/attack [target]` | Attack a target entity | `/attack Goblin Scout` |
| `/endturn` | End your current turn | `/endturn` |
| `/advance` | Advance initiative (DM only) | `/advance` |

### Attack Command Details

1. Select your entity first
2. Type `/attack` followed by target name
3. System rolls attack and damage
4. Results shown in event feed

**Requirements**:
- Must have an entity selected
- Must control the selected entity
- Target must be valid

## Game Mode Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/mode [MODE]` | Change game mode | `/mode COMBAT` |

**Available Modes**:
- `EXPLORATION` - Default exploration mode
- `COMBAT` - Active combat with initiative
- `DIALOGUE` - Social interaction focus
- `CUTSCENE` - Narrative sequence
- `DOWNTIME` - Rest and recovery

## Chat Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/say @target message` | Speak directly to an NPC | `/say @Innkeeper Hello there!` |

### Say Command Details

The `/say` command triggers NPC response:
1. Message is directed to specific NPC
2. NPC generates AI response if audible
3. Both messages appear in event feed

**Format**: `/say @NPCName Your message here`

## AI Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/narrate [context]` | Request AI narration | `/narrate the battle begins` |

### Narrate Command Details

Requests the AI DM to provide narration:
- Optional context helps guide the narration
- Narration appears in purple in event feed
- Uses the campaign's configured DM model

## Chat (No Command)

Type any message **without** a `/` prefix to chat:

```
Hello everyone!
```

This sends a chat message as your controlled character.

**Requirements**:
- Must have session context
- Speaker is your controlled entity (or auto-selected)

## Command Errors

Common error messages:

| Error | Cause | Solution |
|-------|-------|----------|
| "Select an entity first" | No entity selected | Click an entity in the sidebar |
| "You cannot control this entity" | Entity controlled by someone else | Select your own entity |
| "Target not found" | Invalid target name | Check spelling of target name |
| "No encounter selected" | Combat commands need encounter | Select an encounter in right panel |
| "Session context not loaded" | Session not initialized | Refresh the page |

## Tips

- Commands are case-insensitive (`/ROLL` = `/roll`)
- Target names are fuzzy-matched
- Use Tab for command history (if enabled)
- Commands with errors don't consume your turn
