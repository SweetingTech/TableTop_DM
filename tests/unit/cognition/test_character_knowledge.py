from __future__ import annotations

import json
import uuid

import pytest

from cognition.knowledge import search_known_lore
from kernel.lore import LocalLoreIndex, LoreDocument
from tests.unit.cognition.test_character_context import assemble, fixture_context

pytestmark = pytest.mark.unit


def test_public_world_lore_does_not_become_character_knowledge_without_learning():
    scene, actor, event, observation, grant = fixture_context()
    index = LocalLoreIndex()
    document = LoreDocument(
        document_id=uuid.uuid4(),
        world_id=scene.world_id,
        title="Public shrine record",
        text="PUBLIC_UNLEARNED the shrine door opens at sunset.",
        visibility="PUBLIC",
    )
    index.upsert((document,))
    assert index.search(scene.world_id, "PUBLIC_UNLEARNED")
    context = assemble(scene, actor, {}, [], {})
    assert search_known_lore(context.known_lore, "PUBLIC_UNLEARNED") == ()
    assert "PUBLIC_UNLEARNED" not in json.dumps(context.situation())


def test_old_testimony_remains_searchable_without_restoring_the_recent_window():
    scene, actor, event, observation, grant = fixture_context()
    events, grants, observations = {}, {}, []
    for index in range(100):
        text = "The brass gate opens at moonrise." if index == 0 else f"Weather remark {index}."
        source = event.model_copy(
            update={"event_id": uuid.UUID(int=index + 1), "payload": {"text": text}}
        )
        item = observation.model_copy(
            update={
                "observation_id": uuid.UUID(int=index + 501),
                "source_event_id": source.event_id,
                "perceived_payload": source.payload,
            }
        )
        events[source.event_id] = source
        observations.append(item)
        grants[(source.event_id, scene.observer_entity_id)] = grant.model_copy(
            update={"event_id": source.event_id}
        )
    context = assemble(
        scene,
        actor,
        events,
        observations,
        grants,
        event_order={key: n for n, key in enumerate(events)},
    )
    assert len(context.observations) == 80
    assert all("moonrise" not in str(row.perceived_payload) for row in context.observations)
    hits = search_known_lore(context.known_lore, "brass moonrise")
    assert len(hits) == 1 and hits[0].text == "The brass gate opens at moonrise."
    assert hits[0].source_event_id == uuid.UUID(int=1)
    assert "source_event_id" not in json.dumps(hits[0].fiction())


@pytest.mark.parametrize(
    "bad_source", ["operator", "other_branch", "other_world", "no_grant", "masked"]
)
def test_hidden_or_abandoned_sources_cannot_become_retrievable_lore(bad_source):
    scene, actor, event, observation, grant = fixture_context()
    payload = {"text": "HIDDEN_PLOT abandoned testimony."}
    event = event.model_copy(update={"payload": payload})
    observation = observation.model_copy(update={"perceived_payload": payload})
    if bad_source == "operator":
        event = event.model_copy(update={"domain_tags": ("director",)})
    elif bad_source in {"other_branch", "other_world"}:
        field = "branch_id" if bad_source == "other_branch" else "world_id"
        event = event.model_copy(update={field: uuid.uuid4()})
    elif bad_source == "masked":
        grant = grant.model_copy(update={"hidden_payload_fields": frozenset({"text"})})
    grants = {} if bad_source == "no_grant" else {(event.event_id, scene.observer_entity_id): grant}
    context = assemble(scene, actor, {event.event_id: event}, [observation], grants)
    assert search_known_lore(context.known_lore, "HIDDEN_PLOT") == ()
    assert "HIDDEN_PLOT" not in json.dumps(context.situation())


@pytest.mark.parametrize("query,limit", [("x" * 401, 5), ("gate", 0), ("gate", 21)])
def test_knowledge_query_bounds_are_enforced(query, limit):
    with pytest.raises(ValueError):
        search_known_lore((), query, limit=limit)
