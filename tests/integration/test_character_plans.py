from __future__ import annotations

import time
import uuid

import pytest

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_speech_combat_behavior import provoke
from tests.unit.kernel.test_tactical_choices import resources

pytestmark = pytest.mark.integration


def test_committed_recovery_plan_continues_across_runner_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], hp=4, known_spells=("MEND",))
    provoke(admin, base, target, card, "injured-and-under-threat")
    projector = WorldEventProjector(integration_stack.database_url)
    projector.run_once(limit=1000)
    handed = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 3,
            "interval_ms": 100,
            "idempotency_key": "recover-without-player",
        },
    )
    assert handed.status_code == 200, handed.get_json()

    def new_worker():
        worker = create_app(artifact_root=tmp_path).extensions["character_runner"]
        due = worker.controllers.due
        monkeypatch.setattr(
            worker.controllers, "due", lambda: tuple(row for row in due() if str(row.run_id) == run)
        )
        return worker

    def next_decision(worker):
        deadline = time.monotonic() + 3
        while not (due := worker.controllers.due()):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        state = due[0]
        return worker.decisions.decide(
            state.scope, state.executor_actor_id, state.decision_key, state
        )

    first = new_worker()
    withdrawal = next_decision(first)
    assert withdrawal.plan is not None and withdrawal.plan.action == "WITHDRAW"
    assert withdrawal.plan.source_command_id is None and withdrawal.plan.completed_steps == 0
    assert withdrawal.plan.needs.health == 4 and withdrawal.plan.needs.mana == 8
    assert withdrawal.outcome.proposal.parameters == {"dx": -1, "dy": 0}
    assert withdrawal == next_decision(first)
    assert first.run_once() == 1
    projector.run_once(limit=1000)

    restarted = new_worker()
    mend = next_decision(restarted)
    assert mend.plan is not None and mend.plan.action == "MEND"
    assert mend.plan.plan_id == withdrawal.plan.plan_id and mend.plan.completed_steps == 1
    assert mend.plan.source_command_id == withdrawal.outcome.proposal.command_id
    assert mend.outcome.proposal.parameters == {"spell_id": "MEND", "target_id": card["entity_id"]}
    foreign_scope = mend.scope.model_copy(update={"entity_id": uuid.UUID(target)})
    assert (
        restarted.decisions.proposals.find_decision(foreign_scope, mend.actor_id, mend.decision_id)
        is None
    )
    assert restarted.run_once() == 1
    projector.run_once(limit=1000)

    settled = next_decision(restarted)
    assert settled.plan is not None and settled.plan.status == "COMPLETED"
    assert settled.plan.completed_steps == 2 and settled.plan.cooldown_until_step == 4
    assert settled.plan.source_command_id == mend.outcome.proposal.command_id
    assert settled.plan.needs.health == 8 and settled.plan.needs.mana == 6
    assert restarted.run_once() == 1 and restarted.run_once() == 0
    projector.run_once(limit=1000)

    state = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert (state["mode"], state["step"], state["last_error"]) == ("PAUSED", 3, "step_limit")
    scene = player.get(path + "/scene").get_json()
    assert all("plan" not in row for row in scene["recent_observations"])
