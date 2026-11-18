from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from cognition.deliberation import ModelUsage, ProviderCompletion
from kernel.api.app import create_app
from tests.integration.test_controller_runner import setup

pytestmark = pytest.mark.integration


def handoff(player, path, run):
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "expected_epoch": 0,
            "mode": "AUTONOMOUS",
            "max_steps": 1,
            "idempotency_key": "model-stand-in",
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["state"]


def model_worker(root, provider, run, monkeypatch):
    worker = create_app(artifact_root=root, deliberation_provider=provider).extensions[
        "character_runner"
    ]
    due = worker.controllers.due
    monkeypatch.setattr(
        worker.controllers, "due", lambda: tuple(row for row in due() if str(row.run_id) == run)
    )
    return worker


def test_live_compatible_provider_wait_allows_world_progress_and_one_cached_decision(
    integration_stack, monkeypatch, tmp_path
):
    _, (admin, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    assigned = handoff(player, path, run)
    received = []
    calling = threading.Event()
    release = threading.Event()

    class Provider:
        model_version = "campaign-model-fixture"
        runtime_kind = "LOCAL_LLM"

        def complete(self, request):
            received.append(request)
            calling.set()
            assert release.wait(8)
            action = next(name for name in request.allowed_actions if name.endswith("east"))
            return ProviderCompletion(
                content={"action": action, "rationale": "Explore east.", "confidence": 0.8},
                attempts=1,
                usage=ModelUsage(prompt_tokens=62, completion_tokens=12),
            )

    worker = model_worker(tmp_path, Provider(), run, monkeypatch)
    state = worker.controllers.due()[0]

    def decide():
        return worker.decisions.decide(
            state.scope, state.executor_actor_id, state.decision_key, state
        )

    def configure_map():
        return admin.post(
            "/api/v2/commands",
            json={
                "world_id": card["world_id"],
                "branch_id": assigned["branch_id"],
                "run_id": run,
                "command_type": "tabletop.map.configure",
                "idempotency_key": "concurrent-world-commit",
                "parameters": {
                    "zone_id": "world",
                    "name": "Updated campaign map",
                    "min_x": -3,
                    "max_x": 3,
                    "min_y": -3,
                    "max_y": 3,
                },
            },
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(decide)
        try:
            assert calling.wait(4)
            duplicate = pool.submit(decide)
            progress = pool.submit(configure_map).result(timeout=4)
            assert progress.status_code == 200, progress.get_json()
        finally:
            release.set()
        receipt = first.result(timeout=4)
        assert receipt == duplicate.result(timeout=4)

    assert len(received) == 1
    fiction = received[0].model_dump_json()
    for outside_fiction in (
        run,
        assigned["branch_id"],
        assigned["executor_actor_id"],
        "controller_epoch",
    ):
        assert outside_fiction not in fiction
    assert receipt.outcome.tier == "LLM"
    assert receipt.outcome.trace.runtime_kind == "LOCAL_LLM"
    assert receipt.outcome.trace.prompt_contract_version == "character-action-selection-1.0.0"
    assert receipt.outcome.proposal.parameters == {"dx": 1, "dy": 0}
    assert worker.run_once() == 1 and worker.run_once() == 0
    assert len(received) == 1

    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT t.explanation->'deliberation',e.model_version FROM cognition.decision_traces t "
            "JOIN sim.events e ON e.decision_trace_id=t.id WHERE t.id=%s",
            (str(receipt.decision_id),),
        )
        trace, model_version = cursor.fetchone()
        assert model_version == "campaign-model-fixture"
        assert trace["provider_attempts"] == 1
        assert trace["usage"] == {"prompt_tokens": 62, "completion_tokens": 12}


def test_worker_outage_commits_one_deterministic_action_and_records_fallback(
    integration_stack, monkeypatch, tmp_path
):
    _, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    handoff(player, path, run)

    class Unavailable:
        model_version = "offline-fixture"

        def complete(self, request):
            return ProviderCompletion(attempts=2, failure_code="provider_unavailable")

    worker = model_worker(tmp_path, Unavailable(), run, monkeypatch)
    state = worker.controllers.due()[0]
    choice = worker.decisions.decide(
        state.scope, state.executor_actor_id, state.decision_key, state
    )
    assert choice.outcome.tier == "UTILITY"
    assert choice.outcome.trace.fallback_reason == "provider_unavailable"
    assert choice.outcome.deliberation is not None
    assert choice.outcome.deliberation.provider_attempts == 2
    assert choice.outcome.deliberation.model_version == "offline-fixture"
    assert worker.run_once() == 1 and worker.run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert (control["step"], control["mode"], control["last_error"]) == (1, "PAUSED", "step_limit")
