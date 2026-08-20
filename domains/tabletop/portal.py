# ruff: noqa: E501 -- SQL statements retain one-to-one column/value alignment.
from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any, Protocol

import psycopg2.extras
from pydantic import BaseModel, ConfigDict, Field

from identity.models import UserAccount
from identity.repository import IdentityRepository
from identity.service import IdentityService
from kernel.database import transaction

ABILITIES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
CLASSES = (
    "Barbarian",
    "Bard",
    "Cleric",
    "Druid",
    "Fighter",
    "Monk",
    "Paladin",
    "Ranger",
    "Rogue",
    "Sorcerer",
    "Warlock",
    "Wizard",
)
SPECIES = ("Dragonborn", "Dwarf", "Elf", "Gnome", "Goliath", "Halfling", "Human", "Orc", "Tiefling")
BACKGROUNDS = (
    "Acolyte",
    "Artisan",
    "Charlatan",
    "Criminal",
    "Entertainer",
    "Farmer",
    "Guard",
    "Guide",
    "Hermit",
    "Merchant",
    "Noble",
    "Sage",
    "Sailor",
    "Scribe",
    "Soldier",
    "Wayfarer",
)


class CharacterRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    character_id: uuid.UUID
    owner_user_id: uuid.UUID
    world_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    name: str
    species: str
    class_name: str
    background: str
    level: int
    status: str
    current_hit_points: int
    maximum_hit_points: int
    armor_class: int
    speed: int
    ability_scores: dict[str, int]
    sheet: dict[str, Any] = Field(default_factory=dict)
    creation_method: str
    source_filename: str | None = None
    created_at: datetime
    updated_at: datetime


class GameMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    username: str
    display_name: str
    character_id: uuid.UUID | None = None
    character_name: str | None = None
    membership_role: str
    status: str
    joined_at: datetime | None = None


class HostedGame(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: uuid.UUID
    world_id: uuid.UUID
    host_user_id: uuid.UUID
    name: str
    description: str
    status: str
    max_players: int
    safety_notes: str
    house_rules: str
    members: tuple[GameMember, ...] = ()
    created_at: datetime
    updated_at: datetime


class HostedSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: uuid.UUID
    game_id: uuid.UUID
    title: str
    scheduled_for: datetime | None = None
    status: str
    public_notes: str
    dm_notes: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PortalRepository(Protocol):
    def list_characters(
        self, *, owner_user_id: uuid.UUID | None = None
    ) -> tuple[CharacterRecord, ...]: ...
    def get_character(self, character_id: uuid.UUID) -> CharacterRecord | None: ...
    def save_character(self, character: CharacterRecord) -> CharacterRecord: ...
    def delete_character(self, character_id: uuid.UUID) -> None: ...
    def list_games(self) -> tuple[HostedGame, ...]: ...
    def get_game(self, game_id: uuid.UUID) -> HostedGame | None: ...
    def save_game(self, game: HostedGame) -> HostedGame: ...
    def delete_game(self, game_id: uuid.UUID) -> None: ...
    def set_member(self, game_id: uuid.UUID, member: GameMember) -> None: ...
    def remove_member(self, game_id: uuid.UUID, user_id: uuid.UUID) -> None: ...
    def list_sessions(self, game_id: uuid.UUID) -> tuple[HostedSession, ...]: ...
    def save_session(self, session: HostedSession) -> HostedSession: ...


class InMemoryPortalRepository:
    def __init__(self) -> None:
        self.characters: dict[uuid.UUID, CharacterRecord] = {}
        self.games: dict[uuid.UUID, HostedGame] = {}
        self.sessions: dict[uuid.UUID, HostedSession] = {}

    def list_characters(
        self, *, owner_user_id: uuid.UUID | None = None
    ) -> tuple[CharacterRecord, ...]:
        rows = self.characters.values()
        return tuple(
            row for row in rows if owner_user_id is None or row.owner_user_id == owner_user_id
        )

    def get_character(self, character_id: uuid.UUID) -> CharacterRecord | None:
        return self.characters.get(character_id)

    def save_character(self, character: CharacterRecord) -> CharacterRecord:
        self.characters[character.character_id] = character
        return character

    def delete_character(self, character_id: uuid.UUID) -> None:
        if character_id not in self.characters:
            raise KeyError(character_id)
        del self.characters[character_id]

    def list_games(self) -> tuple[HostedGame, ...]:
        return tuple(self.games.values())

    def get_game(self, game_id: uuid.UUID) -> HostedGame | None:
        return self.games.get(game_id)

    def save_game(self, game: HostedGame) -> HostedGame:
        self.games[game.game_id] = game
        return game

    def delete_game(self, game_id: uuid.UUID) -> None:
        if game_id not in self.games:
            raise KeyError(game_id)
        del self.games[game_id]
        self.sessions = {key: row for key, row in self.sessions.items() if row.game_id != game_id}

    def set_member(self, game_id: uuid.UUID, member: GameMember) -> None:
        game = self.games.get(game_id)
        if game is None:
            raise KeyError(game_id)
        members = {row.user_id: row for row in game.members}
        members[member.user_id] = member
        self.games[game_id] = game.model_copy(
            update={"members": tuple(members.values()), "updated_at": datetime.now().astimezone()}
        )

    def remove_member(self, game_id: uuid.UUID, user_id: uuid.UUID) -> None:
        game = self.games.get(game_id)
        if game is None:
            raise KeyError(game_id)
        self.games[game_id] = game.model_copy(
            update={
                "members": tuple(row for row in game.members if row.user_id != user_id),
                "updated_at": datetime.now().astimezone(),
            }
        )

    def list_sessions(self, game_id: uuid.UUID) -> tuple[HostedSession, ...]:
        return tuple(row for row in self.sessions.values() if row.game_id == game_id)

    def save_session(self, session: HostedSession) -> HostedSession:
        self.sessions[session.session_id] = session
        return session


class PostgresPortalRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def list_characters(
        self, *, owner_user_id: uuid.UUID | None = None
    ) -> tuple[CharacterRecord, ...]:
        statement = "SELECT * FROM tabletop.characters"
        parameters: tuple[Any, ...] = ()
        if owner_user_id:
            statement += " WHERE owner_user_id=%s"
            parameters = (str(owner_user_id),)
        statement += " ORDER BY updated_at DESC, name"
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(statement, parameters)
                return tuple(self._character(dict(row)) for row in cursor.fetchall())

    def get_character(self, character_id: uuid.UUID) -> CharacterRecord | None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM tabletop.characters WHERE id=%s", (str(character_id),)
                )
                row = cursor.fetchone()
                return self._character(dict(row)) if row else None

    def save_character(self, character: CharacterRecord) -> CharacterRecord:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tabletop.characters(
                      id,owner_user_id,world_id,entity_id,name,species,class_name,background,level,
                      status,current_hit_points,maximum_hit_points,armor_class,speed,ability_scores,
                      sheet,creation_method,source_filename,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET world_id=excluded.world_id,entity_id=excluded.entity_id,
                      name=excluded.name,species=excluded.species,class_name=excluded.class_name,
                      background=excluded.background,level=excluded.level,status=excluded.status,
                      current_hit_points=excluded.current_hit_points,maximum_hit_points=excluded.maximum_hit_points,
                      armor_class=excluded.armor_class,speed=excluded.speed,ability_scores=excluded.ability_scores,
                      sheet=excluded.sheet,source_filename=excluded.source_filename,updated_at=excluded.updated_at
                    """,
                    (
                        str(character.character_id),
                        str(character.owner_user_id),
                        str(character.world_id) if character.world_id else None,
                        str(character.entity_id) if character.entity_id else None,
                        character.name,
                        character.species,
                        character.class_name,
                        character.background,
                        character.level,
                        character.status,
                        character.current_hit_points,
                        character.maximum_hit_points,
                        character.armor_class,
                        character.speed,
                        psycopg2.extras.Json(character.ability_scores),
                        psycopg2.extras.Json(character.sheet),
                        character.creation_method,
                        character.source_filename,
                        character.created_at,
                        character.updated_at,
                    ),
                )
        return character

    def delete_character(self, character_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM tabletop.characters WHERE id=%s", (str(character_id),))
                if cursor.rowcount != 1:
                    raise KeyError(character_id)

    def list_games(self) -> tuple[HostedGame, ...]:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM tabletop.games ORDER BY updated_at DESC, name")
                rows = tuple(dict(row) for row in cursor.fetchall())
        return tuple(self._game(row, self._members(uuid.UUID(str(row["id"])))) for row in rows)

    def get_game(self, game_id: uuid.UUID) -> HostedGame | None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM tabletop.games WHERE id=%s", (str(game_id),))
                row = cursor.fetchone()
        return self._game(dict(row), self._members(game_id)) if row else None

    def save_game(self, game: HostedGame) -> HostedGame:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tabletop.games(id,world_id,host_user_id,name,description,status,max_players,safety_notes,house_rules,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET name=excluded.name,description=excluded.description,
                      status=excluded.status,max_players=excluded.max_players,safety_notes=excluded.safety_notes,
                      house_rules=excluded.house_rules,updated_at=excluded.updated_at
                    """,
                    (
                        str(game.game_id),
                        str(game.world_id),
                        str(game.host_user_id),
                        game.name,
                        game.description,
                        game.status,
                        game.max_players,
                        game.safety_notes,
                        game.house_rules,
                        game.created_at,
                        game.updated_at,
                    ),
                )
        return game

    def delete_game(self, game_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM tabletop.games WHERE id=%s", (str(game_id),))
                if cursor.rowcount != 1:
                    raise KeyError(game_id)

    def set_member(self, game_id: uuid.UUID, member: GameMember) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tabletop.game_members(game_id,user_id,character_id,membership_role,status,joined_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (game_id,user_id) DO UPDATE SET character_id=excluded.character_id,
                      membership_role=excluded.membership_role,status=excluded.status,joined_at=excluded.joined_at,updated_at=now()
                    """,
                    (
                        str(game_id),
                        str(member.user_id),
                        str(member.character_id) if member.character_id else None,
                        member.membership_role,
                        member.status,
                        member.joined_at,
                    ),
                )

    def remove_member(self, game_id: uuid.UUID, user_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tabletop.game_members WHERE game_id=%s AND user_id=%s",
                    (str(game_id), str(user_id)),
                )

    def list_sessions(self, game_id: uuid.UUID) -> tuple[HostedSession, ...]:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM tabletop.game_sessions WHERE game_id=%s ORDER BY created_at DESC",
                    (str(game_id),),
                )
                return tuple(self._session(dict(row)) for row in cursor.fetchall())

    def save_session(self, session: HostedSession) -> HostedSession:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tabletop.game_sessions(id,game_id,title,scheduled_for,status,public_notes,dm_notes,started_at,ended_at,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET title=excluded.title,scheduled_for=excluded.scheduled_for,
                      status=excluded.status,public_notes=excluded.public_notes,dm_notes=excluded.dm_notes,
                      started_at=excluded.started_at,ended_at=excluded.ended_at,updated_at=excluded.updated_at
                    """,
                    (
                        str(session.session_id),
                        str(session.game_id),
                        session.title,
                        session.scheduled_for,
                        session.status,
                        session.public_notes,
                        session.dm_notes or "",
                        session.started_at,
                        session.ended_at,
                        session.created_at,
                        session.updated_at,
                    ),
                )
        return session

    def _members(self, game_id: uuid.UUID) -> tuple[GameMember, ...]:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT m.*, u.username, p.display_name, c.name AS character_name
                    FROM tabletop.game_members m JOIN identity.users u ON u.id=m.user_id
                    JOIN identity.user_profiles p ON p.user_id=u.id
                    LEFT JOIN tabletop.characters c ON c.id=m.character_id
                    WHERE m.game_id=%s ORDER BY m.membership_role, p.display_name
                    """,
                    (str(game_id),),
                )
                return tuple(
                    GameMember(
                        user_id=uuid.UUID(str(row["user_id"])),
                        username=str(row["username"]),
                        display_name=str(row["display_name"]),
                        character_id=uuid.UUID(str(row["character_id"]))
                        if row["character_id"]
                        else None,
                        character_name=row["character_name"],
                        membership_role=str(row["membership_role"]),
                        status=str(row["status"]),
                        joined_at=row["joined_at"],
                    )
                    for row in cursor.fetchall()
                )

    @staticmethod
    def _character(row: dict[str, Any]) -> CharacterRecord:
        return CharacterRecord(
            character_id=uuid.UUID(str(row["id"])),
            owner_user_id=uuid.UUID(str(row["owner_user_id"])),
            world_id=uuid.UUID(str(row["world_id"])) if row["world_id"] else None,
            entity_id=uuid.UUID(str(row["entity_id"])) if row["entity_id"] else None,
            name=str(row["name"]),
            species=str(row["species"]),
            class_name=str(row["class_name"]),
            background=str(row["background"]),
            level=int(row["level"]),
            status=str(row["status"]),
            current_hit_points=int(row["current_hit_points"]),
            maximum_hit_points=int(row["maximum_hit_points"]),
            armor_class=int(row["armor_class"]),
            speed=int(row["speed"]),
            ability_scores=dict(row["ability_scores"]),
            sheet=dict(row["sheet"]),
            creation_method=str(row["creation_method"]),
            source_filename=row["source_filename"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _game(row: dict[str, Any], members: tuple[GameMember, ...]) -> HostedGame:
        return HostedGame(
            game_id=uuid.UUID(str(row["id"])),
            world_id=uuid.UUID(str(row["world_id"])),
            host_user_id=uuid.UUID(str(row["host_user_id"])),
            name=str(row["name"]),
            description=str(row["description"]),
            status=str(row["status"]),
            max_players=int(row["max_players"]),
            safety_notes=str(row["safety_notes"]),
            house_rules=str(row["house_rules"]),
            members=members,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _session(row: dict[str, Any]) -> HostedSession:
        return HostedSession(
            session_id=uuid.UUID(str(row["id"])),
            game_id=uuid.UUID(str(row["game_id"])),
            title=str(row["title"]),
            scheduled_for=row["scheduled_for"],
            status=str(row["status"]),
            public_notes=str(row["public_notes"]),
            dm_notes=str(row["dm_notes"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class TabletopPortalService:
    def __init__(self, repository: PortalRepository, identities: IdentityRepository) -> None:
        self.repository = repository
        self.identities = identities

    def list_characters(self, actor: UserAccount) -> tuple[CharacterRecord, ...]:
        self._require_player(actor)
        return self.repository.list_characters(
            owner_user_id=None if actor.is_admin else actor.user_id
        )

    def create_character(self, actor: UserAccount, payload: dict[str, Any]) -> CharacterRecord:
        self._require_player(actor)
        method = str(payload.get("creation_method", "BUILT")).upper()
        seed = int(payload.get("seed", random.SystemRandom().randrange(1, 2**31)))
        generated = self._generated(seed) if method == "GENERATED" else {}
        values = {**generated, **payload}
        scores = self._scores(values.get("ability_scores", {}))
        maximum = int(values.get("maximum_hit_points", 10))
        current = int(values.get("current_hit_points", maximum))
        now = datetime.now().astimezone()
        character = CharacterRecord(
            character_id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            world_id=uuid.UUID(str(values["world_id"])) if values.get("world_id") else None,
            name=str(values.get("name") or generated.get("name") or "Unnamed Adventurer").strip(),
            species=str(values.get("species", "Human")),
            class_name=str(values.get("class_name", "Fighter")),
            background=str(values.get("background", "Adventurer")),
            level=int(values.get("level", 1)),
            status=str(values.get("status", "ALIVE")).upper(),
            current_hit_points=current,
            maximum_hit_points=maximum,
            armor_class=int(values.get("armor_class", 10)),
            speed=int(values.get("speed", 30)),
            ability_scores=scores,
            sheet=dict(values.get("sheet", {})),
            creation_method=method,
            source_filename=values.get("source_filename"),
            created_at=now,
            updated_at=now,
        )
        self._validate_character(character)
        return self.repository.save_character(character)

    def update_character(
        self, actor: UserAccount, character_id: uuid.UUID, payload: dict[str, Any]
    ) -> CharacterRecord:
        existing = self._character(character_id)
        if not actor.is_admin and existing.owner_user_id != actor.user_id:
            raise PermissionError("only the character owner can edit this character")
        allowed = {
            "name",
            "species",
            "class_name",
            "background",
            "level",
            "status",
            "current_hit_points",
            "maximum_hit_points",
            "armor_class",
            "speed",
            "ability_scores",
            "sheet",
            "world_id",
        }
        updates = {key: value for key, value in payload.items() if key in allowed}
        if "world_id" in updates and updates["world_id"]:
            updates["world_id"] = uuid.UUID(str(updates["world_id"]))
        if "ability_scores" in updates:
            updates["ability_scores"] = self._scores(updates["ability_scores"])
        updates["updated_at"] = datetime.now().astimezone()
        character = existing.model_copy(update=updates)
        self._validate_character(character)
        return self.repository.save_character(character)

    def delete_character(self, actor: UserAccount, character_id: uuid.UUID) -> None:
        existing = self._character(character_id)
        if not actor.is_admin and existing.owner_user_id != actor.user_id:
            raise PermissionError("only the character owner can delete this character")
        self.repository.delete_character(character_id)

    def list_games(self, actor: UserAccount) -> tuple[HostedGame, ...]:
        if not actor.is_admin and not actor.has_player_role and not actor.has_dm_role:
            raise PermissionError("a Player or Dungeon Master role is required")
        games = self.repository.list_games()
        if actor.is_admin:
            return games
        return tuple(
            game
            for game in games
            if game.host_user_id == actor.user_id
            or any(member.user_id == actor.user_id for member in game.members)
        )

    def create_game(self, actor: UserAccount, payload: dict[str, Any]) -> HostedGame:
        world_id = uuid.UUID(str(payload["world_id"]))
        IdentityService.require_world_role(actor, world_id, "DM")
        now = datetime.now().astimezone()
        game = HostedGame(
            game_id=uuid.uuid4(),
            world_id=world_id,
            host_user_id=actor.user_id,
            name=str(payload["name"]).strip(),
            description=str(payload.get("description", "")),
            status=str(payload.get("status", "PLANNING")).upper(),
            max_players=int(payload.get("max_players", 6)),
            safety_notes=str(payload.get("safety_notes", "")),
            house_rules=str(payload.get("house_rules", "")),
            created_at=now,
            updated_at=now,
        )
        return self.repository.save_game(game)

    def update_game(
        self, actor: UserAccount, game_id: uuid.UUID, payload: dict[str, Any]
    ) -> HostedGame:
        game = self._hosted(actor, game_id)
        allowed = {"name", "description", "status", "max_players", "safety_notes", "house_rules"}
        updates = {key: value for key, value in payload.items() if key in allowed}
        if "status" in updates:
            updates["status"] = str(updates["status"]).upper()
        updates["updated_at"] = datetime.now().astimezone()
        return self.repository.save_game(game.model_copy(update=updates))

    def delete_game(self, actor: UserAccount, game_id: uuid.UUID) -> None:
        self._hosted(actor, game_id)
        self.repository.delete_game(game_id)

    def set_member(
        self, actor: UserAccount, game_id: uuid.UUID, payload: dict[str, Any]
    ) -> HostedGame:
        game = self._hosted(actor, game_id)
        user_id = uuid.UUID(str(payload["user_id"]))
        account = self.identities.get_account(user_id)
        if account is None:
            raise KeyError(user_id)
        membership_role = str(payload.get("membership_role", "PLAYER")).upper()
        required = "DM" if membership_role == "CO_DM" else "PLAYER"
        IdentityService.require_world_role(account, game.world_id, required)
        character_id = (
            uuid.UUID(str(payload["character_id"])) if payload.get("character_id") else None
        )
        character = self.repository.get_character(character_id) if character_id else None
        if character and character.owner_user_id != user_id:
            raise ValueError("assigned character must belong to the selected user")
        member = GameMember(
            user_id=user_id,
            username=account.username,
            display_name=account.profile.display_name,
            character_id=character_id,
            character_name=character.name if character else None,
            membership_role=membership_role,
            status=str(payload.get("status", "INVITED")).upper(),
            joined_at=datetime.now().astimezone()
            if payload.get("status") in {"JOINED", "READY"}
            else None,
        )
        self.repository.set_member(game_id, member)
        return self.repository.get_game(game_id) or game

    def remove_member(self, actor: UserAccount, game_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self._hosted(actor, game_id)
        self.repository.remove_member(game_id, user_id)

    def list_sessions(self, actor: UserAccount, game_id: uuid.UUID) -> tuple[HostedSession, ...]:
        game = self._game(game_id)
        if (
            not actor.is_admin
            and game.host_user_id != actor.user_id
            and not any(member.user_id == actor.user_id for member in game.members)
        ):
            raise PermissionError("game membership required")
        dm_view = (
            actor.is_admin
            or game.host_user_id == actor.user_id
            or any(
                member.user_id == actor.user_id and member.membership_role == "CO_DM"
                for member in game.members
            )
        )
        rows = self.repository.list_sessions(game_id)
        return rows if dm_view else tuple(row.model_copy(update={"dm_notes": None}) for row in rows)

    def save_session(
        self,
        actor: UserAccount,
        game_id: uuid.UUID,
        payload: dict[str, Any],
        session_id: uuid.UUID | None = None,
    ) -> HostedSession:
        self._hosted(actor, game_id)
        existing = next(
            (row for row in self.repository.list_sessions(game_id) if row.session_id == session_id),
            None,
        )
        now = datetime.now().astimezone()
        status = str(payload.get("status", existing.status if existing else "SCHEDULED")).upper()
        started = existing.started_at if existing else None
        ended = existing.ended_at if existing else None
        if status == "LIVE" and started is None:
            started = now
        if status in {"COMPLETED", "CANCELLED"} and started is not None:
            ended = now
        session = HostedSession(
            session_id=session_id or uuid.uuid4(),
            game_id=game_id,
            title=str(payload.get("title", existing.title if existing else "Game Session")),
            scheduled_for=payload.get(
                "scheduled_for", existing.scheduled_for if existing else None
            ),
            status=status,
            public_notes=str(
                payload.get("public_notes", existing.public_notes if existing else "")
            ),
            dm_notes=str(payload.get("dm_notes", existing.dm_notes if existing else "")),
            started_at=started,
            ended_at=ended,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        return self.repository.save_session(session)

    def _hosted(self, actor: UserAccount, game_id: uuid.UUID) -> HostedGame:
        game = self._game(game_id)
        co_dm = any(
            member.user_id == actor.user_id and member.membership_role == "CO_DM"
            for member in game.members
        )
        if not actor.is_admin and game.host_user_id != actor.user_id and not co_dm:
            raise PermissionError("DM access to this game is required")
        return game

    def _game(self, game_id: uuid.UUID) -> HostedGame:
        game = self.repository.get_game(game_id)
        if game is None:
            raise KeyError(game_id)
        return game

    def _character(self, character_id: uuid.UUID) -> CharacterRecord:
        character = self.repository.get_character(character_id)
        if character is None:
            raise KeyError(character_id)
        return character

    @staticmethod
    def _require_player(actor: UserAccount) -> None:
        if not actor.is_admin and not actor.has_player_role:
            raise PermissionError("a Player role is required")

    @staticmethod
    def _generated(seed: int) -> dict[str, Any]:
        rng = random.Random(seed)
        class_name = rng.choice(CLASSES)
        species = rng.choice(SPECIES)
        background = rng.choice(BACKGROUNDS)
        names = ("Arden", "Bryn", "Cael", "Dara", "Elian", "Fenn", "Kaia", "Mira", "Orin", "Tamsin")
        scores = [15, 14, 13, 12, 10, 8]
        rng.shuffle(scores)
        maximum = rng.randint(8, 14)
        return {
            "name": rng.choice(names),
            "class_name": class_name,
            "species": species,
            "background": background,
            "ability_scores": dict(zip(ABILITIES, scores, strict=True)),
            "maximum_hit_points": maximum,
            "current_hit_points": maximum,
            "armor_class": rng.randint(11, 16),
            "speed": 30,
            "sheet": {"generation_seed": seed},
        }

    @staticmethod
    def _scores(raw: Any) -> dict[str, int]:
        values = dict(raw) if isinstance(raw, dict) else {}
        return {ability: int(values.get(ability, 10)) for ability in ABILITIES}

    @staticmethod
    def _validate_character(character: CharacterRecord) -> None:
        if not character.name.strip():
            raise ValueError("character name is required")
        if character.level < 1 or character.level > 20:
            raise ValueError("character level must be between 1 and 20")
        if (
            character.maximum_hit_points < 1
            or character.current_hit_points < 0
            or character.current_hit_points > character.maximum_hit_points
        ):
            raise ValueError("character hit points are invalid")
        if any(score < 1 or score > 30 for score in character.ability_scores.values()):
            raise ValueError("ability scores must be between 1 and 30")
