from __future__ import annotations

import uuid
from dataclasses import replace

import psycopg2
import pytest
from pydantic import BaseModel

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_speech_combat_behavior import provoke
from tests.unit.kernel.test_tactical_choices import command, resources

pytestmark = pytest.mark.integration


def durable_mark(stack, base):
    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.version,p.state_hash,"
            "(SELECT count(*) FROM sim.command_log WHERE branch_id=p.branch_id),"
            "(SELECT count(*) FROM sim.events WHERE branch_id=p.branch_id),"
            "(SELECT count(*) FROM sim.outbox o JOIN sim.events e ON e.event_id=o.event_id "
            " WHERE e.branch_id=p.branch_id) "
            "FROM sim.branch_projections p WHERE p.branch_id=%s",
            (base["branch_id"],),
        )
        return cursor.fetchone()


def player_after_restart(root, player):
    app = create_app(artifact_root=root)
    client = app.test_client()
    client.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    return app, client


def test_human_and_separate_runner_use_learned_fixed_spells_with_atomic_rejection_and_retry(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], known_spells=("MEND",))
    before = durable_mark(integration_stack, base)
    for kind, parameters in [
        ("tabletop.combat.attack", {"target_id": target, "attack_bonus": 30}),
        ("tabletop.magic.cast", {"target_id": card["entity_id"], "spell_id": "MEND", "power": 999}),
        (
            "tabletop.magic.invoke",
            {"target_id": card["entity_id"], "spell_id": "MEND", "mana_cost": 0},
        ),
        ("tabletop.magic.invoke", {"target_id": target, "spell_id": "ARCANE_BOLT"}),
    ]:
        response = command(player, base, card, kind, parameters, "failed-intent")
        assert response.status_code == 400, response.get_json()
        assert durable_mark(integration_stack, base) == before
    intent = {"spell_id": "MEND", "target_id": card["entity_id"]}
    healed = command(player, base, card, "tabletop.magic.cast", intent, "failed-intent")
    assert healed.status_code == 200, healed.get_json()
    assert healed.get_json()["result"]["result"]["power"] == 4
    after = durable_mark(integration_stack, base)
    restarted_app, restarted = player_after_restart(tmp_path, player)
    retried = command(restarted, base, card, "tabletop.magic.cast", intent, "failed-intent")
    assert retried.get_json() == healed.get_json()
    assert durable_mark(integration_stack, base) == after
    # The character's actual learned list survives restart and restricts its runner's candidates.
    resources(app, admin, base, card["entity_id"], known_spells=("MEND",))
    provoke(admin, base, target, card, "new-threat")
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    _, restarted = player_after_restart(tmp_path, player)
    context = restarted.get(path + "/context", query_string={"run_id": run}).get_json()
    spells = [
        c for c in context["action_candidates"] if c["command_type"] == "tabletop.magic.invoke"
    ]
    assert [c["parameters"]["spell_id"] for c in spells] == ["MEND"]
    assert (
        restarted.post(
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
    worker = create_app(artifact_root=tmp_path)
    assert worker.extensions["character_runner"].run_once() == 1
    reader, _ = player_after_restart(tmp_path, player)
    state = reader.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert body["hp"] == 9 and body["mana"] == 6 and body["known_spells"] == ["MEND"]
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.parameters,e.payload FROM sim.command_log c JOIN sim.events e "
            "ON (c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key) "
            "WHERE c.run_id=%s AND c.decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        parameters, payload = cursor.fetchone()
        assert parameters == intent and payload["power"] == 4
        assert payload["rules_version"] == "tabletop-action-rules-1.0.0"


def test_legacy_attack_receipt_retries_after_strict_request_upgrade_and_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    sim = app.extensions["simulation"]
    current = sim.bus.definition("tabletop.combat.attack")

    class LegacyAttack(BaseModel):
        target_id: uuid.UUID
        attack_bonus: int = 0

    def legacy_handler(proposal, state):
        return current.handler(
            proposal.model_copy(
                update={"parameters": {"target_id": proposal.parameters["target_id"]}}
            ),
            state,
        )

    proposal = CommandProposal(
        **base,
        actor_id=uuid.UUID(str(app.extensions["demo_ids"]["actor_id"])),
        embodied_entity_id=uuid.UUID(target),
        command_type="tabletop.combat.attack",
        parameters={"target_id": card["entity_id"], "attack_bonus": 30},
        idempotency_key="legacy-committed-attack",
        seed=2,
    )
    legacy = replace(current, request_model=LegacyAttack, handler=legacy_handler, version="1.0.0")
    original = sim.durable_repository.execute(
        proposal, sim.authority(proposal.world_id, proposal.actor_id), legacy
    )
    before = durable_mark(integration_stack, base)
    restored = create_app(artifact_root=tmp_path).extensions["simulation"]
    receipt = restored.submit(proposal)
    assert receipt == original and durable_mark(integration_stack, base) == before
    with pytest.raises(ValueError, match="Invalid"):
        restored.submit(proposal.model_copy(update={"idempotency_key": "new-legacy-attack"}))
    assert durable_mark(integration_stack, base) == before
