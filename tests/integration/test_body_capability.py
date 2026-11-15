from __future__ import annotations

import uuid

import pytest

from tests.integration.test_action_rules import durable_mark
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_speech_combat_behavior import prepare

pytestmark = pytest.mark.integration


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
