from __future__ import annotations

import pytest

from cognition.models import RelationshipVector
from cognition.relationships import RelationshipEngine, RelationshipModifiers

pytestmark = pytest.mark.unit


def test_relationship_deltas_are_modified_and_clamped():
    before = RelationshipVector(trust=95, affection=4, respect=2, resentment=90)
    engine = RelationshipEngine()

    saved = engine.apply(before, "saved_life")
    humiliated = engine.apply(
        saved.after,
        "public_humiliation",
        modifiers=RelationshipModifiers(
            betrayal_sensitivity="HIGH",
            forgiveness="LOW",
        ),
    )

    assert saved.after.trust == 100
    assert saved.applied_deltas["trust"] == 5
    assert humiliated.after.affection == 2
    assert humiliated.after.respect == -7
    assert humiliated.after.resentment == 100
    assert before.trust == 95


def test_attraction_requires_explicit_content_permission():
    vector = RelationshipVector()
    engine = RelationshipEngine()

    denied = engine.apply(vector, "custom", deltas={"attraction": 20})
    permitted = engine.apply(
        vector,
        "custom",
        deltas={"attraction": 20},
        modifiers=RelationshipModifiers(attraction_permitted=True),
    )

    assert denied.after.attraction is None
    assert "attraction" not in denied.applied_deltas
    assert permitted.after.attraction == 20


def test_unknown_relationship_axis_is_rejected():
    with pytest.raises(ValueError, match="Unknown relationship axes"):
        RelationshipEngine().apply(RelationshipVector(), "custom", deltas={"telepathy": 10})


def test_unknown_relationship_event_cannot_create_empty_causal_change():
    with pytest.raises(ValueError, match="Unknown relationship event type"):
        RelationshipEngine().apply(RelationshipVector(), "invented_reaction")

    with pytest.raises(ValueError, match="Relationship deltas cannot be empty"):
        RelationshipEngine().apply(RelationshipVector(), "invented_reaction", deltas={})
