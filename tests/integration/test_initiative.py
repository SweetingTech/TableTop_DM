from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from domains.tabletop.action_time import wait_seconds
from domains.tabletop.initiative import ENCOUNTERS
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.errors import BodyActionPending
from tests.integration.test_action_rules import durable_mark
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_initiative_api import ordered, start_encounter

pytestmark = pytest.mark.integration


def test_seeded_order_restart_late_retry_and_ledger_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app, game)
    admin, player, card, path, run, target, base = game
    identity = receipt["result"]["result"]["encounter_id"]
    expected = state.projections[ENCOUNTERS][identity]
    advance_clock(admin, base, 7)
    restored, client = fresh_client(tmp_path)
    branch = uuid.UUID(base["branch_id"])
    current = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert current.projections[ENCOUNTERS][identity] == expected
    first, second = ordered(receipt)
    assert wait_seconds(current, uuid.UUID(first)) == 5
    assert wait_seconds(current, uuid.UUID(second)) == 0
    mark = durable_mark(integration_stack, base)
    response = client.post(
        "/api/v2/commands",
        json={
            **base,
            "actor_id": receipt["event"]["actor_id"],
            "command_type": "tabletop.encounter.start",
            "parameters": {"participants": [target, card["entity_id"]]},
            "idempotency_key": "initiative",
            "seed": 999,
        },
    )
    assert response.status_code == 200, response.get_json()
    for field in ("result", "event", "state_hash"):
        assert response.get_json()[field] == receipt[field]
    assert durable_mark(integration_stack, base) == mark
    replay = client.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_concurrent_initiative_actions_reserve_once_and_out_of_turn_does_not_write(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app, game)
    admin, player, card, path, run, target, base = game
    first, second = map(uuid.UUID, ordered(receipt))
    sim = app.extensions["world_runner"].snapshot()
    branch = uuid.UUID(base["branch_id"])
    actor_id = sim.entities[(branch, first)].controller_actor_id
    request = CommandProposal(
        **base,
        actor_id=actor_id,
        embodied_entity_id=first,
        command_type="tabletop.combat.guard",
        parameters={},
        idempotency_key="guard",
    )
    actor = sim.authority(request.world_id, request.actor_id)
    sources = [create_app(artifact_root=tmp_path).extensions["simulation"] for _ in range(2)]
    mark = durable_mark(integration_stack, base)

    def execute(index):
        try:
            sources[index].durable_repository.execute(
                request.model_copy(
                    update={"command_id": uuid.uuid4(), "idempotency_key": f"race-{index}"}
                ),
                actor,
                sources[index].bus.definition(request.command_type),
            )
            return "committed"
        except BodyActionPending:
            return "waiting"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(execute, range(2))) == ["committed", "waiting"]
    after = durable_mark(integration_stack, base)
    assert after[0] == mark[0] + 1
    blocked = request.model_copy(
        update={
            "command_id": uuid.uuid4(),
            "idempotency_key": "wrong-turn",
            "embodied_entity_id": second,
            "actor_id": sim.entities[(branch, second)].controller_actor_id,
        }
    )
    with pytest.raises(BodyActionPending):
        sources[0].durable_repository.execute(
            blocked,
            sim.authority(blocked.world_id, blocked.actor_id),
            sources[0].bus.definition(blocked.command_type),
        )
    assert durable_mark(integration_stack, base) == after


def test_failed_initiative_commit_rolls_back_order_seed_projection_and_ledger(
    integration_stack, monkeypatch, tmp_path
):
    from kernel.postgres_repository import PostgresCommandRepository

    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    branch = uuid.UUID(base["branch_id"])
    state = app.extensions["world_runner"].snapshot().states.get(branch)
    original_hash = state.state_hash
    mark = durable_mark(integration_stack, base)
    original = PostgresCommandRepository._insert_event

    def fail(cursor, event):
        original(cursor, event)
        raise ValueError("injected initiative publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        response = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.encounter.start",
                "parameters": {"participants": [card["entity_id"], target]},
                "idempotency_key": "failed-initiative",
            },
        )
        assert response.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, client = fresh_client(tmp_path)
    fresh = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert fresh.state_hash == original_hash and not fresh.projections.get(ENCOUNTERS)
    _, current, receipt = start_encounter(restored, (client, player, card, path, run, target, base))
    assert receipt["result"]["result"]["randomness"]["branch_sequence"] == mark[2] + 1
