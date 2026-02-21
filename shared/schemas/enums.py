from enum import Enum


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"
    ARCHIVED = "ARCHIVED"
    TOMBSTONED = "TOMBSTONED"
    PURGED = "PURGED"


class GameMode(str, Enum):
    EXPLORATION = "EXPLORATION"
    SOCIAL = "SOCIAL"
    COMBAT = "COMBAT"
    CUTSCENE = "CUTSCENE"
    PAUSED = "PAUSED"


VALID_MODE_TRANSITIONS = {
    GameMode.EXPLORATION: {
        GameMode.SOCIAL,
        GameMode.COMBAT,
        GameMode.CUTSCENE,
        GameMode.PAUSED,
    },
    GameMode.SOCIAL: {
        GameMode.EXPLORATION,
        GameMode.COMBAT,
        GameMode.CUTSCENE,
        GameMode.PAUSED,
    },
    GameMode.COMBAT: {
        GameMode.EXPLORATION,
        GameMode.SOCIAL,
        GameMode.CUTSCENE,
        GameMode.PAUSED,
    },
    GameMode.CUTSCENE: {
        GameMode.EXPLORATION,
        GameMode.SOCIAL,
        GameMode.COMBAT,
        GameMode.PAUSED,
    },
    GameMode.PAUSED: {
        GameMode.EXPLORATION,
        GameMode.SOCIAL,
        GameMode.COMBAT,
        GameMode.CUTSCENE,
    },
}


class PrincipalType(str, Enum):
    HUMAN = "HUMAN"
    AI_DM = "AI_DM"
    AI_NPC = "AI_NPC"
    AI_GOD = "AI_GOD"
    SYSTEM = "SYSTEM"


class CampaignRole(str, Enum):
    GM = "GM"
    PLAYER = "PLAYER"
    OBSERVER = "OBSERVER"
    GOD_OPERATOR = "GOD_OPERATOR"
    SYSTEM = "SYSTEM"


class EntityType(str, Enum):
    PC = "PC"
    NPC = "NPC"
    MONSTER = "MONSTER"
    ITEM = "ITEM"
    LOCATION = "LOCATION"
    FACTION = "FACTION"
    GOD = "GOD"


class EncounterStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class EventType(str, Enum):
    CHAT = "CHAT"
    OOC = "OOC"
    INTENT = "INTENT"
    REACTION = "REACTION"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    STATE_DELTA = "STATE_DELTA"
    NARRATION = "NARRATION"
    DIALOGUE = "DIALOGUE"
    SYSTEM = "SYSTEM"
    SYSTEM_WARNING = "SYSTEM_WARNING"


class ControlledBy(str, Enum):
    PLAYER = "PLAYER"
    AI_DM = "AI_DM"
    AI_NPC = "AI_NPC"
    AI_GOD = "AI_GOD"
    SYSTEM = "SYSTEM"


class TensionLevel(str, Enum):
    CALM = "CALM"
    SUSPICIOUS = "SUSPICIOUS"
    HOSTILE = "HOSTILE"
    WEAPONS_DRAWN = "WEAPONS_DRAWN"
    COMBAT = "COMBAT"


TENSION_LADDER = [
    TensionLevel.CALM,
    TensionLevel.SUSPICIOUS,
    TensionLevel.HOSTILE,
    TensionLevel.WEAPONS_DRAWN,
    TensionLevel.COMBAT,
]


class ContentRating(str, Enum):
    SAFE = "SAFE"
    MATURE = "MATURE"
    EXPLICIT = "EXPLICIT"


class TriggerType(str, Enum):
    ON_MOVEMENT = "ON_MOVEMENT"
    ON_ATTACKED = "ON_ATTACKED"
    ON_CAST = "ON_CAST"
    ON_DAMAGED = "ON_DAMAGED"
    ON_ALLY_DAMAGED = "ON_ALLY_DAMAGED"


class ConditionType(str, Enum):
    BLINDED = "BLINDED"
    CHARMED = "CHARMED"
    DEAFENED = "DEAFENED"
    FRIGHTENED = "FRIGHTENED"
    GRAPPLED = "GRAPPLED"
    INCAPACITATED = "INCAPACITATED"
    INVISIBLE = "INVISIBLE"
    PARALYZED = "PARALYZED"
    PETRIFIED = "PETRIFIED"
    POISONED = "POISONED"
    PRONE = "PRONE"
    RESTRAINED = "RESTRAINED"
    STUNNED = "STUNNED"
    UNCONSCIOUS = "UNCONSCIOUS"
    EXHAUSTION = "EXHAUSTION"


class SummaryScope(str, Enum):
    GLOBAL = "GLOBAL"
    PRINCIPAL = "PRINCIPAL"
