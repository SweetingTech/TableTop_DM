from __future__ import annotations

import uuid

import pytest

from cognition.relationship_evidence import classify_relationship
from kernel.api.app import create_app
from kernel.contracts import EventEnvelopeV2

pytestmark = pytest.mark.unit


def test_relationship_updates_require_authorized_same_branch_event_and_are_idempotent(
    tmp_path,
) -> None:
    app = create_app(artifact_root=tmp_path)
    simulation = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    target_id = next(
        entity.entity_id
        for entity in simulation.entities.values()
        if entity.entity_id != ids["hero_id"]
    )

    with app.test_client() as client:
        command = client.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.console.submit",
                "world_id": str(ids["world_id"]),
                "branch_id": str(ids["branch_id"]),
                "run_id": str(ids["run_id"]),
                "actor_id": str(ids["actor_id"]),
                "embodied_entity_id": str(ids["hero_id"]),
                "parameters": {"text": "I keep my promise."},
                "idempotency_key": "relationship-causality-source",
            },
        )
        source_event_id = command.get_json()["event"]["event_id"]
        endpoint = f"/api/v2/entities/{ids['hero_id']}/relationships"

        missing_source = client.post(
            endpoint,
            json={"target_entity_id": str(target_id), "event_type": "kept_promise"},
        )
        unauthorized_actor = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Relationship intruder",
                "kind": "HUMAN",
                "roles": [],
                "capabilities": [],
            },
        ).get_json()
        unauthorized = client.post(
            endpoint,
            headers={"X-TTDM-Actor-ID": unauthorized_actor["actor_id"]},
            json={
                "target_entity_id": str(target_id),
                "source_event_id": source_event_id,
                "event_type": "kept_promise",
            },
        )

        other_world = simulation.create_world("Relationship audit world")
        other_run = next(
            run for run in simulation.runs.values() if run.world_id == other_world.world_id
        )
        wrong_branch_event = EventEnvelopeV2(
            world_id=other_world.world_id,
            branch_id=other_world.canonical_branch_id,
            run_id=other_run.run_id,
            actor_id=ids["actor_id"],
            event_type="test.wrong_branch",
            visible_to=(ids["actor_id"],),
            correlation_id=uuid.uuid4(),
        )
        simulation.events[wrong_branch_event.event_id] = wrong_branch_event
        wrong_branch = client.post(
            endpoint,
            json={
                "target_entity_id": str(target_id),
                "source_event_id": str(wrong_branch_event.event_id),
                "event_type": "kept_promise",
            },
        )

        payload = {
            "target_entity_id": str(target_id),
            "source_event_id": source_event_id,
            "event_type": "kept_promise",
        }
        first = client.post(endpoint, json=payload)
        retry = client.post(endpoint, json=payload)
        conflicting_retry = client.post(
            endpoint,
            json={**payload, "event_type": "saved_life"},
        )
        mind = client.get(f"/api/v2/entities/{ids['hero_id']}/mind").get_json()

    assert command.status_code == 200
    assert missing_source.status_code == 400
    assert unauthorized.status_code == 403
    assert wrong_branch.status_code == 400
    assert first.status_code == retry.status_code == 201
    assert first.get_json() == retry.get_json()
    assert first.get_json()["source_event_id"] == source_event_id
    assert first.get_json()["after"]["trust"] == 12
    assert conflicting_retry.status_code == 400
    assert mind["relationships"][0]["trust"] == 12
    assert len(mind["relationship_changes"]) == 1


def test_controlled_actor_uses_only_visible_registered_relationship_events(
    tmp_path,
) -> None:
    app = create_app(artifact_root=tmp_path)
    simulation = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    target_id = next(
        entity.entity_id
        for entity in simulation.entities.values()
        if entity.entity_id != ids["hero_id"]
    )

    with app.test_client() as client:
        controller = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Controlled relationship actor",
                "kind": "AGENT",
                "world_id": str(ids["world_id"]),
                "roles": ["NPC"],
                "capabilities": [
                    "world.read",
                    "entity.control",
                    "action.propose",
                    "action.commit",
                ],
            },
        ).get_json()
        source = client.post(
            f"/api/v2/worlds/{ids['world_id']}/entities",
            json={
                "name": "Controlled witness",
                "entity_type": "NPC",
                "controller_actor_id": controller["actor_id"],
                "public_state": {"x": 5, "y": 5},
            },
        ).get_json()
        own_event = client.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.console.submit",
                "world_id": str(ids["world_id"]),
                "branch_id": str(ids["branch_id"]),
                "run_id": str(ids["run_id"]),
                "actor_id": controller["actor_id"],
                "embodied_entity_id": source["entity_id"],
                "parameters": {"text": "I saw the promise kept."},
                "idempotency_key": "controlled-relationship-source",
            },
        ).get_json()["event"]
        hidden_event = client.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.console.submit",
                "world_id": str(ids["world_id"]),
                "branch_id": str(ids["branch_id"]),
                "run_id": str(ids["run_id"]),
                "actor_id": str(ids["actor_id"]),
                "embodied_entity_id": str(ids["hero_id"]),
                "parameters": {"text": "A private GM event."},
                "idempotency_key": "hidden-relationship-source",
            },
        ).get_json()["event"]
        endpoint = f"/api/v2/entities/{source['entity_id']}/relationships"
        headers = {"X-TTDM-Actor-ID": controller["actor_id"]}
        base = {
            "target_entity_id": str(target_id),
            "source_event_id": own_event["event_id"],
            "event_type": "kept_promise",
        }

        mapped = client.post(endpoint, headers=headers, json=base)
        explicit_delta = client.post(
            endpoint,
            headers=headers,
            json={**base, "deltas": {"trust": 99}},
        )
        custom_modifier = client.post(
            endpoint,
            headers=headers,
            json={**base, "modifiers": {"forgiveness": "LOW"}},
        )
        unknown_mapping = client.post(
            endpoint,
            headers=headers,
            json={**base, "event_type": "invented_reaction"},
        )
        hidden = client.post(
            endpoint,
            headers=headers,
            json={**base, "source_event_id": hidden_event["event_id"]},
        )

    assert mapped.status_code == 403
    assert explicit_delta.status_code == 403
    assert custom_modifier.status_code == 403
    assert unknown_mapping.status_code == 403
    assert hidden.status_code == 403


def physical_relationship_game(app, admin=None, scope=None):
    ids = scope or app.extensions["demo_ids"]
    client = admin or app.test_client()
    world, branch, run, actor = (
        str(ids[k]) for k in ("world_id", "branch_id", "run_id", "actor_id")
    )
    controller = client.post(
        "/api/v2/actors",
        json={
            "world_id": world,
            "display_name": "Relationship witness",
            "kind": "AGENT",
            "capabilities": [
                "world.read",
                "entity.control",
                "entity.act",
                "action.propose",
                "action.commit",
            ],
        },
    ).get_json()
    entities = []
    for name, owner, y in [("Witness", controller["actor_id"], 5), ("Speaker", actor, 6)]:
        response = client.post(
            f"/api/v2/worlds/{world}/entities",
            json={
                "name": name,
                "entity_type": "NPC",
                "controller_actor_id": owner,
                "public_state": {"x": 5, "y": y, "hp": 20, "max_hp": 20, "armor": 10},
            },
        )
        assert response.status_code == 201, response.get_json()
        entities.append(response.get_json()["entity_id"])
    observer, target = entities
    base = {"world_id": world, "branch_id": branch, "run_id": run, "actor_id": actor}

    def speak(key):
        response = client.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.dialogue.speak",
                "embodied_entity_id": target,
                "idempotency_key": key,
                "parameters": {"text": "Hello, neighbor."},
            },
        )
        assert response.status_code == 200, response.get_json()
        return response.get_json()["event"]["event_id"]

    return client, base, controller["actor_id"], observer, target, speak


def check_grounded_relationships(game):
    client, base, controller, observer, target, speak = game
    source = speak("heard-one")
    endpoint = f"/api/v2/entities/{observer}/relationships"
    headers = {"X-TTDM-Actor-ID": controller}
    payload = {"target_entity_id": target, "source_event_id": source}
    for reaction in ("saved_life", "kept_promise", "public_humiliation"):
        response = client.post(endpoint, headers=headers, json={**payload, "event_type": reaction})
        assert response.status_code == 400, response.get_json()
    first = client.post(endpoint, headers=headers, json=payload)
    assert first.status_code == 201, first.get_json()
    assert first.get_json()["event_type"] == "conversation"
    assert first.get_json()["after"]["familiarity"] == 1
    assert first.get_json()["after"]["trust"] == 0
    assert first.get_json()["policy_version"] == "relationship-evidence-1.0.0"
    second = client.post(
        endpoint, headers=headers, json={**payload, "source_event_id": speak("heard-two")}
    )
    assert second.status_code == 201, second.get_json()
    assert second.get_json()["after"]["familiarity"] == 2
    assert client.post(endpoint, headers=headers, json=payload).get_json() == first.get_json()
    return endpoint, headers, payload, first.get_json()


def test_controlled_reactions_follow_frozen_heard_evidence_and_retry_old_history(tmp_path):
    app = create_app(artifact_root=tmp_path)
    check_grounded_relationships(physical_relationship_game(app))


def test_attack_reaction_requires_the_actual_perceived_attacker_and_victim(tmp_path):
    app = create_app(artifact_root=tmp_path)
    client, base, controller, observer, target, speak = physical_relationship_game(app)
    event = client.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.combat.attack",
            "embodied_entity_id": target,
            "seed": 1,
            "idempotency_key": "actual-attack",
            "parameters": {"target_id": observer, "attack_bonus": 30, "damage_sides": 2},
        },
    )
    assert event.status_code == 200, event.get_json()
    response = client.post(
        f"/api/v2/entities/{observer}/relationships",
        headers={"X-TTDM-Actor-ID": controller},
        json={"target_entity_id": target, "source_event_id": event.get_json()["event"]["event_id"]},
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["event_type"] == "attacked"
    assert response.get_json()["after"]["trust"] == -12


@pytest.mark.parametrize("mask", ["speaker", "text", "empty", "wrong_observer", "director"])
def test_relationship_classifier_rejects_missing_masked_or_nonphysical_facts(tmp_path, mask):
    app = create_app(artifact_root=tmp_path)
    client, base, controller, observer, target, speak = physical_relationship_game(app)
    sim = app.extensions["simulation"]
    event = sim.events[uuid.UUID(speak("masked-source"))]
    grant = sim.perception_grant(event.event_id, uuid.UUID(observer))
    assert grant is not None
    if mask in {"speaker", "text"}:
        grant = grant.model_copy(
            update={
                "hidden_payload_fields": frozenset(
                    {"speaker_entity_id" if mask == "speaker" else "text"}
                )
            }
        )
    elif mask == "empty":
        grant = grant.model_copy(update={"modalities": ()})
    elif mask == "wrong_observer":
        grant = grant.model_copy(update={"observer_entity_id": uuid.uuid4()})
    else:
        event = event.model_copy(update={"domain_tags": ("operator",)})
    with pytest.raises((ValueError, PermissionError)):
        classify_relationship(
            event, grant, uuid.UUID(observer), uuid.UUID(target), uuid.UUID(controller)
        )
