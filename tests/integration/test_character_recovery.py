from __future__ import annotations

import time

import pytest

from cognition.projector import WorldEventProjector
from tests.integration.test_character_deliberation import model_worker
from tests.integration.test_controller_runner import setup

pytestmark = pytest.mark.integration


def test_movement_recovery_uses_committed_history_after_runner_restart(
    integration_stack, monkeypatch, tmp_path
):
    _, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "expected_epoch": 0,
            "mode": "AUTONOMOUS",
            "max_steps": 5,
            "interval_ms": 100,
            "idempotency_key": "recover-after-restart",
        },
    )
    assert response.status_code == 200, response.get_json()

    class Model:
        model_version = "recovery-model-fixture"

        def __init__(self, direction):
            self.direction = direction
            self.calls = []

        def complete(self, request):
            self.calls.append(request)
            action = next(
                (name for name in request.allowed_actions if name.endswith(self.direction)),
                next(name for name in request.allowed_actions if name.endswith("north")),
            )
            return {"action": action, "rationale": "Look for an open path.", "confidence": 1}

    def wait_for_controller(worker):
        deadline = time.monotonic() + 6
        while not (due := worker.controllers.due()):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        return due[0]

    model = Model("east")
    worker = model_worker(tmp_path, model, run, monkeypatch)
    projector = WorldEventProjector(integration_stack.database_url)
    for direction in ("east", "west", "east", "west"):
        model.direction = direction
        current = wait_for_controller(worker)
        assert worker.run_once() == 1, (current.step, direction)
        projector.run_once(limit=1000)
    assert len(model.calls) == 4

    fresh_model = Model("east")
    restarted = model_worker(tmp_path, fresh_model, run, monkeypatch)
    current = wait_for_controller(restarted)
    decision = restarted.decisions.decide(
        current.scope, current.executor_actor_id, current.decision_key, current
    )
    assert current.step == 4 and decision.recovery is not None
    assert decision.recovery.reasons == ("no_movement_progress",)
    assert decision.outcome.proposal.parameters == {"dx": 0, "dy": -1}
    assert not any(name.endswith("east") for name in fresh_model.calls[0].allowed_actions)
    assert restarted.run_once() == 1 and restarted.run_once() == 0
    assert len(fresh_model.calls) == 1
    final = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert final["step"] == 5 and final["last_error"] == "step_limit"
