import uuid

import pytest
from pydantic import ValidationError

from domains.tabletop.character_identity import IDENTITY_SHEET_KEY, CharacterIdentity
from domains.tabletop.portal import (
    InMemoryPortalRepository,
    PostgresPortalRepository,
    TabletopPortalService,
)
from identity.repository import InMemoryIdentityRepository
from identity.service import IdentityService

pytestmark = pytest.mark.unit


def portal_and_owner():
    identities = InMemoryIdentityRepository()
    owner, _ = IdentityService(identities).login("admin", "admin123")
    return TabletopPortalService(InMemoryPortalRepository(), identities), owner


@pytest.mark.parametrize(
    "payload",
    [
        {"backstory": "x" * 12001},
        {"motives": ["x"] * 21},
        {"values": ["x" * 501]},
        {"bonds": ["   "]},
        {"secrets": [7]},
        {"initial_known_facts": "a string"},
        {"dm_notes": "hidden director instructions"},
        {"backstory": None},
    ],
)
def test_identity_rejects_unbounded_or_untyped_authored_data(payload):
    with pytest.raises(ValidationError):
        CharacterIdentity.model_validate(payload)


def test_card_content_version_tracks_identity_not_wounds_ownership_or_binding():
    portal, owner = portal_and_owner()
    card = portal.create_character(
        owner,
        {
            "name": "Nyra",
            "authored_identity": {
                "backstory": " Raised in a port. ",
                "motives": [" Find my sister. "],
                "secrets": ["I hid the map."],
            },
        },
    )
    assert card.authored_identity.backstory == "Raised in a port."
    assert card.authored_identity.motives == ("Find my sister.",)
    assert len(card.card_version) == 64
    wounded = portal.update_character(owner, card.character_id, {"current_hit_points": 1})
    assert wounded.card_version == card.card_version
    rebound = wounded.model_copy(update={"entity_id": uuid.uuid4(), "world_id": uuid.uuid4()})
    assert rebound.card_version == card.card_version
    edited = portal.update_character(
        owner,
        card.character_id,
        {
            "authored_identity": {**card.authored_identity.model_dump(), "values": ["Mercy"]},
        },
    )
    assert edited.card_version != card.card_version
    assert card.authored_identity.values == ()
    assert (
        portal.update_character(
            owner,
            card.character_id,
            {
                "authored_identity": edited.authored_identity.model_dump(),
            },
        ).card_version
        == edited.card_version
    )


def test_sheet_edits_cannot_bypass_identity_validation_and_other_sheet_data_survives():
    portal, owner = portal_and_owner()
    card = portal.create_character(
        owner,
        {
            "name": "Nyra",
            "sheet": {"equipment": ["rope"]},
            "authored_identity": {"initial_known_facts": ["The ferry sails at dawn."]},
        },
    )
    updated = portal.update_character(owner, card.character_id, {"sheet": {"equipment": ["torch"]}})
    assert updated.authored_identity == card.authored_identity
    assert updated.sheet == {"equipment": ["torch"]}
    with pytest.raises(ValueError, match="authored_identity field"):
        portal.update_character(owner, card.character_id, {"sheet": {IDENTITY_SHEET_KEY: {}}})
    with pytest.raises(ValidationError):
        portal.update_character(
            owner, card.character_id, {"authored_identity": {"values": [False]}}
        )
    assert portal.repository.get_character(card.character_id) == updated


def test_legacy_private_sheet_hydrates_without_changing_equipment():
    portal, owner = portal_and_owner()
    card = portal.create_character(owner, {"name": "Old hero", "sheet": {"equipment": ["rope"]}})
    row = card.model_dump(exclude={"card_version", "authored_identity", "character_id"})
    row["id"] = card.character_id
    restored = PostgresPortalRepository._character(row)
    assert restored.authored_identity == CharacterIdentity()
    assert restored.card_version == card.card_version
    assert restored.sheet == {"equipment": ["rope"]}


def test_rejected_create_does_not_save_partial_character():
    portal, owner = portal_and_owner()
    with pytest.raises(ValueError, match="authored_identity field"):
        portal.create_character(owner, {"sheet": {IDENTITY_SHEET_KEY: {"secrets": ["x"]}}})
    assert portal.repository.list_characters() == ()
