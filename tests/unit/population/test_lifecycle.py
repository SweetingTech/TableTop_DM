from __future__ import annotations

import uuid

import pytest

from population.lifecycle import PopulationLifecycle
from population.models import PopulationLevel

pytestmark = pytest.mark.unit


def test_lazy_materialize_activate_deactivate_preserves_history_and_mind_state():
    persona_id = uuid.UUID(int=900)
    lifecycle = PopulationLifecycle()
    profile = {"persona_id": str(persona_id), "occupation": "merchant"}

    materialized = lifecycle.materialize(
        persona_id,
        profile=profile,
        persistent_state={"finances": {"coins": 10}, "history": ["arrived"]},
        world_step=4,
    )
    active = lifecycle.activate(
        persona_id,
        active_state={
            "beliefs": ["market is unsafe"],
            "memories": ["a theft"],
            "relationships": {"guard": {"trust": -10}},
            "finances": {"coins": 8},
            "transient_path": [1, 2, 3],
        },
        world_step=5,
    )
    inactive = lifecycle.deactivate(
        persona_id,
        compressed_state={"occupation": "merchant"},
        world_step=9,
    )

    assert materialized.level is PopulationLevel.MATERIALIZED
    assert active.level is PopulationLevel.ACTIVE
    assert inactive.level is PopulationLevel.MATERIALIZED
    assert inactive.active_state == {}
    assert inactive.persistent_state["beliefs"] == ["market is unsafe"]
    assert inactive.persistent_state["finances"] == {"coins": 8}
    assert "transient_path" not in inactive.persistent_state
    assert [item.to_level for item in lifecycle.history] == [
        PopulationLevel.MATERIALIZED,
        PopulationLevel.ACTIVE,
        PopulationLevel.MATERIALIZED,
    ]
    assert [item.sequence for item in lifecycle.history] == [1, 2, 3]


def test_lifecycle_rejects_invalid_transitions_and_profile_replacement():
    persona_id = uuid.UUID(int=901)
    lifecycle = PopulationLifecycle()
    lifecycle.register(persona_id, {"name": "one"})

    with pytest.raises(ValueError, match="profile cannot be replaced"):
        lifecycle.register(persona_id, {"name": "two"})
    with pytest.raises(ValueError, match="Cannot activate a STATISTICAL"):
        lifecycle.activate(persona_id, active_state={}, world_step=1)

    lifecycle.materialize(persona_id, world_step=3)
    lifecycle.activate(
        persona_id,
        active_state={"beliefs": ["temporary"]},
        world_step=4,
    )
    inactive = lifecycle.deactivate(
        persona_id,
        world_step=5,
        preserve_fields=frozenset(),
    )
    assert "beliefs" not in inactive.persistent_state
    lifecycle.activate(persona_id, active_state={}, world_step=6)
    with pytest.raises(ValueError, match="cannot move backward"):
        lifecycle.deactivate(persona_id, world_step=5)
