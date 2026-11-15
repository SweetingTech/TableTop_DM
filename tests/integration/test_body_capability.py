from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandResult, StateDelta
from tests.integration.test_action_rules import durable_mark
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_speech_combat_behavior import prepare

pytestmark = pytest.mark.integration


def test_durable_stand_in_stun_and_generation_race_preserve_budget_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )

    class StunRequest(BaseModel):
        stunned: bool

    def change(proposal, state):
        requested = StunRequest.model_validate(proposal.parameters)
        return CommandResult(
            result={"updated": True},
            deltas=(
                StateDelta(
                    projection="tabletop.entities",
                    operation="MERGE",
                    entity_id=uuid.UUID(card["entity_id"]),
                    values={"conditions": ["stunned"] if requested.stunned else []},
                ),
            ),
            domain_tags=("operator",),
        )

    app.extensions["simulation"].bus.register(
        CommandDefinition(
            command_type="test.body_stun",
            required_capabilities=frozenset({"entity.control"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
            handler=change,
            request_model=StunRequest,
        )
    )

    def stun(value):
        result = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "test.body_stun",
                "parameters": {"stunned": value},
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        assert result.status_code == 200, result.get_json()

    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 3,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    stun(True)
    worker = create_app(artifact_root=tmp_path).extensions["character_runner"]
    for _ in range(4):
        assert worker.run_once() == 0

    def control():
        return player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]

    assert control()["mode"] == "AUTONOMOUS" and control()["failures"] == control()["step"] == 0
    stun(False)
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    original = worker.decisions.decide

    def race(*args, **kwargs):
        receipt = original(*args, **kwargs)
        stun(True)
        return receipt

    monkeypatch.setattr(worker.decisions, "decide", race)
    assert worker.run_once() == 0
    assert control()["failures"] == control()["step"] == 0
    restored = create_app(artifact_root=tmp_path).extensions["character_runner"]
    assert restored.run_once() == 0
    assert control()["failures"] == control()["step"] == 0
    stun(False)
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    assert restored.run_once() == 1
    assert control()["failures"] == 0 and control()["step"] == 1


def test_incapacity_and_human_combat_wakeup_are_atomic_and_survive_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )

    def spawn(name, **values):
        response = admin.post(
            f"/api/v2/worlds/{base['world_id']}/entities",
            json={
                "name": name,
                "entity_type": "NPC",
                "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
                "public_state": {"x": 2, "y": 0, "hp": 10, "max_hp": 20, "mana": 4, **values},
            },
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()["entity_id"]

    stunned = spawn("Stunned", conditions=["stunned"])
    asleep = spawn("Sleeper", asleep=True)
    dead = spawn("Dead with stale positive HP", status="DEAD")
    scene = admin.get(
        f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/entities/{stunned}/scene"
    )
    assert scene.status_code == 200
    own = next(row for row in scene.get_json()["perceived_entities"] if row["entity_id"] == stunned)
    assert own["status"] == "INCAPACITATED"

    def action(client, entity, command, parameters, key):
        return client.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": entity,
                "command_type": command,
                "parameters": parameters,
                "idempotency_key": key,
            },
        )

    before = durable_mark(integration_stack, base)
    for command, parameters in [
        ("tabletop.spatial.move", {"dx": 0, "dy": 1}),
        ("tabletop.dialogue.speak", {"text": "Cannot speak while stunned."}),
        ("tabletop.combat.guard", {}),
    ]:
        response = action(admin, stunned, command, parameters, command)
        assert response.status_code == 400, response.get_json()
        assert durable_mark(integration_stack, base) == before
    # A failed spell does not wake the human-controlled sleeper or spend its mana.
    response = action(
        admin,
        asleep,
        "tabletop.magic.invoke",
        {
            "spell_id": "MEND",
            "target_id": dead,
        },
        "failed-healing",
    )
    assert response.status_code == 400, response.get_json()
    assert durable_mark(integration_stack, base) == before
    _, operator = fresh_client(tmp_path)
    assert (
        action(operator, stunned, "tabletop.combat.guard", {}, "still-stunned").status_code == 400
    )
    assert durable_mark(integration_stack, base) == before
    response = action(
        operator,
        asleep,
        "tabletop.magic.invoke",
        {
            "spell_id": "MEND",
            "target_id": asleep,
        },
        "wake-and-mend",
    )
    assert response.status_code == 200, response.get_json()
    committed = durable_mark(integration_stack, base)
    restored, operator = fresh_client(tmp_path)
    retry = action(
        operator,
        asleep,
        "tabletop.magic.invoke",
        {
            "spell_id": "MEND",
            "target_id": asleep,
        },
        "wake-and-mend",
    )
    assert retry.get_json() == response.get_json()
    assert durable_mark(integration_stack, base) == committed
    body = (
        restored.extensions["simulation"]
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][asleep]
    )
    assert body["asleep"] is False and body["mana"] == 2 and body["hp"] == 14
    replay = operator.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
