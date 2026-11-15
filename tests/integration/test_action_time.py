from __future__ import annotations

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from cognition.projector import WorldEventProjector
from domains.tabletop import register_tabletop
from domains.tabletop.action_time import ACTION_TIME
from kernel.api.app import create_app
from kernel.command_bus import CommandBus
from kernel.contracts import CommandProposal
from kernel.errors import BodyActionPending
from kernel.state import InMemoryStateStore
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock, clock_path
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.integration


def test_camera_modes_preserve_busy_body_and_reservation_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    assert (
        command(
            player,
            base,
            card,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "THIRD_PERSON"},
            "ready-camera",
        ).status_code
        == 200
    )
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
    restarted, client = player_after_restart(tmp_path, player)
    branch = uuid.UUID(base["branch_id"])
    before = restarted.extensions["world_runner"].snapshot().states.get(branch)
    bodies, timing = (
        copy.deepcopy(before.projections["tabletop.entities"]),
        copy.deepcopy(before.projections[ACTION_TIME]),
    )
    first = command(
        client,
        base,
        card,
        "tabletop.battlefield.set_control_mode",
        {"camera_mode": "FIRST_PERSON"},
        "busy-camera",
    )
    assert first.status_code == 200, first.get_json()
    after = restarted.extensions["world_runner"].snapshot().states.get(branch)
    assert (
        after.projections["tabletop.entities"] == bodies
        and after.projections[ACTION_TIME] == timing
    )
    mark = durable_mark(integration_stack, base)
    assert (
        command(
            client,
            base,
            card,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "FIRST_PERSON"},
            "busy-camera",
        ).get_json()
        == first.get_json()
    )
    assert durable_mark(integration_stack, base) == mark
    assert (
        command(
            client, base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "still-busy"
        ).status_code
        == 400
    )
    assert durable_mark(integration_stack, base) == mark


def test_cost_effect_parity_restart_retry_and_replay(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], hp=5, mana=8)
    sim = app.extensions["world_runner"].snapshot()
    branch, entity = uuid.UUID(base["branch_id"]), uuid.UUID(card["entity_id"])
    actor_id = sim.entities[(branch, entity)].controller_actor_id
    request = CommandProposal(
        **base,
        actor_id=actor_id,
        embodied_entity_id=entity,
        command_type="tabletop.combat.guard",
        parameters={},
        idempotency_key="guard",
    )
    store = InMemoryStateStore()
    store.add(sim.states.get(branch).working_copy())
    reference = register_tabletop(CommandBus(store))
    reference.execute(request, sim.authority(request.world_id, actor_id))
    first = player.post("/api/v2/commands", json=request.model_dump(mode="json"))
    assert first.status_code == 200, first.get_json()
    assert (
        app.extensions["world_runner"].snapshot().states.get(branch).state_hash
        == store.get(branch).state_hash
    )
    mark = durable_mark(integration_stack, base)
    restarted, client = player_after_restart(tmp_path, player)
    assert (
        client.post("/api/v2/commands", json=request.model_dump(mode="json")).get_json()
        == first.get_json()
    )
    assert (
        command(
            client, base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "early"
        ).status_code
        == 400
    )
    assert durable_mark(integration_stack, base) == mark
    advance_clock(admin, base, 6)
    scene = client.get(path + "/scene").get_json()
    own = next(row for row in scene["perceived_entities"] if row["entity_id"] == str(entity))
    assert own["action_wait_seconds"] == 0 and not own["guarded"]
    ready_mark = durable_mark(integration_stack, base)
    invalid = command(
        client,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "MEND", "target_id": str(uuid.uuid4())},
        "invalid-target",
    )
    assert invalid.status_code == 400
    assert durable_mark(integration_stack, base) == ready_mark
    healed = command(
        client,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "MEND", "target_id": str(entity)},
        "mend",
    )
    assert healed.status_code == 200, healed.get_json()
    after_heal = durable_mark(integration_stack, base)
    restored, again = player_after_restart(tmp_path, client)
    assert (
        command(
            again,
            base,
            card,
            "tabletop.magic.invoke",
            {"spell_id": "MEND", "target_id": str(entity)},
            "mend",
        ).get_json()
        == healed.get_json()
    )
    assert durable_mark(integration_stack, base) == after_heal
    state = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert state.projections["tabletop.entities"][str(entity)]["hp"] == 9
    assert state.projections["tabletop.entities"][str(entity)]["mana"] == 6
    assert state.projections[ACTION_TIME][str(entity)]["ready_seconds"] == 12
    _, operator = fresh_client(tmp_path)
    replay = operator.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_real_transactions_reserve_body_once(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    sim = app.extensions["world_runner"].snapshot()
    entity = uuid.UUID(card["entity_id"])
    request = CommandProposal(
        **base,
        actor_id=sim.entities[(uuid.UUID(base["branch_id"]), entity)].controller_actor_id,
        embodied_entity_id=entity,
        command_type="tabletop.spatial.move",
        parameters={"dx": 1, "dy": 0},
        idempotency_key="move",
    )
    actor = sim.authority(request.world_id, request.actor_id)
    sources = [create_app(artifact_root=tmp_path).extensions["simulation"] for _ in range(2)]
    mark = durable_mark(integration_stack, base)

    def execute(index):
        try:
            sources[index].durable_repository.execute(
                request.model_copy(
                    update={"command_id": uuid.uuid4(), "idempotency_key": f"worker-{index}"}
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
    assert after[2:] == tuple(value + 1 for value in mark[2:])
    own = next(
        row
        for row in player.get(path + "/scene").get_json()["perceived_entities"]
        if row["entity_id"] == str(entity)
    )
    assert own["position"]["x"] == 1 and own["action_wait_seconds"] == 1


def test_restarted_autonomous_runner_waits_without_budget_loss(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    clock = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": False,
            "seconds_per_tick": 6,
        },
        "resume",
    )
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 1,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    restarted, client = player_after_restart(tmp_path, player)
    runner = restarted.extensions["character_runner"]
    before = client.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    mark = durable_mark(integration_stack, base)
    for _ in range(4):
        assert runner.run_once() == 0
    assert (
        client.get(path + "/control", query_string={"run_id": run}).get_json()["control"] == before
    )
    assert durable_mark(integration_stack, base) == mark
    assert restarted.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    assert runner.run_once() == 1
    control = client.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == 1 and control["failures"] == 0
