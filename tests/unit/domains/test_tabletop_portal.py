import uuid

from domains.tabletop.portal import InMemoryPortalRepository, TabletopPortalService
from identity.models import UserProfile
from identity.repository import InMemoryIdentityRepository
from identity.service import IdentityService


def test_player_builds_generates_and_tracks_character_status() -> None:
    identities = InMemoryIdentityRepository()
    identity = IdentityService(identities)
    administrator, _ = identity.login("admin", "admin123")
    world_id = uuid.uuid4()
    player = identity.create_user(
        administrator,
        username="mira",
        temporary_password="Temporary-Player-2026!",
        profile=UserProfile(display_name="Mira"),
    )
    player = identity.set_world_roles(
        administrator, player.user_id, world_id, frozenset({"PLAYER"})
    )
    portal = TabletopPortalService(InMemoryPortalRepository(), identities)

    built = portal.create_character(
        player,
        {
            "world_id": str(world_id),
            "name": "Nyra",
            "species": "Elf",
            "class_name": "Ranger",
            "maximum_hit_points": 12,
            "creation_method": "BUILT",
        },
    )
    generated = portal.create_character(
        player, {"world_id": str(world_id), "creation_method": "GENERATED", "seed": 42}
    )
    dead = portal.update_character(
        player, built.character_id, {"status": "DEAD", "current_hit_points": 0}
    )

    assert dead.status == "DEAD"
    assert dead.current_hit_points == 0
    assert generated.creation_method == "GENERATED"
    assert (
        portal.create_character(
            player,
            {
                "name": "Imported Hero",
                "species": "Human",
                "class_name": "Wizard",
                "creation_method": "IMPORTED",
                "source_filename": "hero.json",
            },
        ).source_filename
        == "hero.json"
    )


def test_dm_hosts_game_manages_roster_and_private_session_notes() -> None:
    identities = InMemoryIdentityRepository()
    identity = IdentityService(identities)
    administrator, _ = identity.login("admin", "admin123")
    world_id = uuid.uuid4()
    dm = identity.create_user(
        administrator,
        username="dungeonmaster",
        temporary_password="Temporary-DungeonMaster-2026!",
        profile=UserProfile(display_name="Morgan"),
    )
    dm = identity.set_world_roles(administrator, dm.user_id, world_id, frozenset({"DM"}))
    player = identity.create_user(
        administrator,
        username="playerone",
        temporary_password="Temporary-Player-2026!",
        profile=UserProfile(display_name="Taylor"),
    )
    player = identity.set_world_roles(
        administrator, player.user_id, world_id, frozenset({"PLAYER"})
    )
    portal = TabletopPortalService(InMemoryPortalRepository(), identities)
    character = portal.create_character(
        player,
        {"name": "Brindle", "world_id": str(world_id), "creation_method": "GENERATED", "seed": 7},
    )
    game = portal.create_game(dm, {"world_id": str(world_id), "name": "Keep on the Borderlands"})
    game = portal.set_member(
        dm,
        game.game_id,
        {
            "user_id": str(player.user_id),
            "character_id": str(character.character_id),
            "status": "READY",
        },
    )
    session = portal.save_session(
        dm,
        game.game_id,
        {
            "title": "Session Zero",
            "status": "LIVE",
            "public_notes": "Meet the party",
            "dm_notes": "Secret patron",
        },
    )

    assert game.members[0].character_name == "Brindle"
    assert session.started_at is not None
    assert portal.list_sessions(player, game.game_id)[0].dm_notes is None
