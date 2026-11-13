from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from domains.tabletop.portal import CharacterRecord, InMemoryPortalRepository
from kernel.state import stable_hash

pytestmark = pytest.mark.unit


def test_authored_history_isolated_from_runtime_changes_and_return_to_old_content():
    now = datetime.now(UTC)
    card = CharacterRecord(
        character_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        name="Élan",
        species="Elf",
        class_name="Ranger",
        background="Sailor",
        level=1,
        status="ALIVE",
        current_hit_points=10,
        maximum_hit_points=10,
        armor_class=12,
        speed=30,
        ability_scores={"wisdom": 14},
        creation_method="BUILT",
        created_at=now,
        updated_at=now,
    )
    repository = InMemoryPortalRepository()
    repository.save_character(card)
    original_hash = stable_hash(
        {
            "schema": "character-card-1.0.0",
            "name": card.name,
            "species": card.species,
            "class_name": card.class_name,
            "background": card.background,
            "level": card.level,
            "ability_scores": card.ability_scores,
            "authored_identity": card.authored_identity.model_dump(mode="json"),
        }
    )
    assert card.card_version == original_hash
    repository.save_character(
        card.model_copy(update={"current_hit_points": 2, "entity_id": uuid.uuid4()})
    )
    assert len(repository.character_revisions(card.character_id, actor_id=uuid.uuid4())) == 1
    changed = card.model_copy(update={"name": "New name"})
    repository.save_character(changed)
    repository.save_character(card)
    revisions = repository.character_revisions(card.character_id, actor_id=uuid.uuid4())
    assert [row.revision_number for row in revisions] == [1, 2, 3]
    assert revisions[0].card_version == revisions[2].card_version == original_hash
    assert revisions[0].revision_id != revisions[2].revision_id
    revisions[0].content.ability_scores["wisdom"] = 99
    assert (
        repository.character_revisions(card.character_id, actor_id=uuid.uuid4())[
            0
        ].content.ability_scores["wisdom"]
        == 14
    )
    repository.delete_character(card.character_id)
    assert not repository.character_revisions(card.character_id, actor_id=uuid.uuid4())
