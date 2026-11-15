from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from domains.tabletop import register_tabletop
from kernel.command_bus import CommandBus
from kernel.contracts import CommandProposal
from kernel.randomness import allocate_randomness
from kernel.state import InMemoryStateStore
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_speech_combat_behavior import prepare

pytestmark = pytest.mark.integration


def test_durable_rng_matches_reference_retries_after_restart_and_serializes_workers(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    sim = app.extensions["simulation"]
    request = CommandProposal(
        **base,
        actor_id=sim.entities[
            (uuid.UUID(base["branch_id"]), uuid.UUID(card["entity_id"]))
        ].controller_actor_id,
        embodied_entity_id=uuid.UUID(card["entity_id"]),
        command_type="tabletop.combat.attack",
        parameters={"target_id": target},
        idempotency_key="same-text-first",
        seed=41,
    )
    actor = sim.authority(request.world_id, request.actor_id)
    before = sim.states.get(request.branch_id).working_copy()
    store = InMemoryStateStore()
    store.add(before.working_copy())
    reference = register_tabletop(CommandBus(store))
    with psycopg2.connect(integration_stack.admin_url) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT seed FROM sim.runs WHERE id=%s", (run,))
        run_seed = cursor.fetchone()[0]
    reference.run_seed_reader = lambda _: run_seed
    expected = reference.execute(request.model_copy(update={"seed": 999}), actor)
    response = player.post("/api/v2/commands", json=request.model_dump(mode="json"))
    assert response.status_code == 200, response.get_json()
    actual = response.get_json()["result"]["result"]
    assert actual == expected.result.result
    assert (
        actual["randomness"]
        == allocate_randomness(run_seed, before.version + 1, request.command_type).model_dump()
    )
    after_first = durable_mark(integration_stack, base)
    restarted, client = player_after_restart(tmp_path, player)
    retried = client.post(
        "/api/v2/commands", json=request.model_copy(update={"seed": -1}).model_dump(mode="json")
    )
    assert retried.get_json() == response.get_json()
    assert durable_mark(integration_stack, base) == after_first
    # An invalid target neither consumes a logical slot nor leaves ledger writes.
    failed = request.model_copy(
        update={"idempotency_key": "invalid", "parameters": {"target_id": str(uuid.uuid4())}}
    )
    assert client.post("/api/v2/commands", json=failed.model_dump(mode="json")).status_code == 400
    assert durable_mark(integration_stack, base) == after_first

    repository = restarted.extensions["simulation"].durable_repository
    definition = restarted.extensions["simulation"].bus.definition(request.command_type)

    def execute(index):
        return repository.execute(
            request.model_copy(
                update={
                    "command_id": uuid.uuid4(),
                    "idempotency_key": f"worker-{index}",
                    "seed": 41,
                }
            ),
            actor,
            definition,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(execute, range(4)))
    proofs = [r.result.result["randomness"] for r in receipts]
    assert sorted(p["branch_sequence"] for p in proofs) == list(
        range(before.version + 2, before.version + 6)
    )
    assert len({p["action_seed"] for p in proofs}) == 4
    assert actual["randomness"]["action_seed"] not in {p["action_seed"] for p in proofs}
    assert all("randomness" not in str(p) for r in receipts for p in r.perceptions)
    assert client.get(f"/api/v2/branches/{base['branch_id']}/replay").status_code == 403
    _, operator = fresh_client(tmp_path)
    replay = operator.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
