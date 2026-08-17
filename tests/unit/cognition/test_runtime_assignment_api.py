from __future__ import annotations

import uuid

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def test_runtime_assignment_api_authorizes_lineage_and_bounds_auto_decision(tmp_path) -> None:
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    scope = {
        "world_id": str(ids["world_id"]),
        "branch_id": str(ids["branch_id"]),
        "run_id": str(ids["run_id"]),
    }
    runtime_url = f"/api/v2/entities/{ids['hero_id']}/runtime"
    actions = [
        {
            "action": "advance",
            "command_type": "tabletop.console.submit",
            "parameters": {"text": "I advance."},
            "utility_factors": {"goal_alignment": 0.7},
        },
        {
            "action": "wait",
            "command_type": "tabletop.console.submit",
            "parameters": {"text": "/wait"},
            "utility_factors": {"goal_alignment": 0.69},
        },
    ]

    with app.test_client() as client:
        persona = client.post(
            "/api/v2/personas/generate", json={"seed": 889, "fixed": {}}
        ).get_json()
        decision = {
            "persona_id": persona["persona_id"],
            "seed": 31,
            "actor_id": str(ids["actor_id"]),
            "embodied_entity_id": str(ids["hero_id"]),
            **scope,
            "actions": actions,
            "novel_or_ambiguous": True,
            "planning_goal": {"advanced": True},
            "planning_actions": [{"name": "advance", "effects": {"advanced": True}, "cost": 1}],
        }
        absent = client.get(runtime_url, query_string=scope)
        default_decision = client.post(
            "/api/v2/cognition/decide",
            json={**decision, "idempotency_key": "runtime-default"},
        )
        outsider = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Runtime outsider",
                "kind": "HUMAN",
                "world_id": scope["world_id"],
                "roles": [],
                "capabilities": [],
            },
        ).get_json()
        denied = client.put(
            runtime_url,
            headers={"X-TTDM-Actor-ID": outsider["actor_id"]},
            json={**scope, "runtime_kind": "UTILITY"},
        )
        wrong_run = client.put(
            runtime_url,
            json={**scope, "run_id": str(uuid.uuid4()), "runtime_kind": "UTILITY"},
        )
        local = client.put(
            runtime_url,
            json={
                **scope,
                "runtime_kind": "LOCAL_LLM",
                "runtime_config": {"model": "local-test"},
            },
        )
        loaded = client.get(runtime_url, query_string=scope)
        local_decision = client.post(
            "/api/v2/cognition/decide",
            json={
                **decision,
                "planning_goal": {},
                "planning_actions": [],
                "idempotency_key": "runtime-local",
            },
        )
        utility = client.put(
            runtime_url,
            json={**scope, "runtime_kind": "UTILITY"},
        )
        utility_decision = client.post(
            "/api/v2/cognition/decide",
            json={
                **decision,
                "allow_llm": True,
                "idempotency_key": "runtime-utility",
            },
        )
        human = client.put(
            runtime_url,
            json={**scope, "runtime_kind": "HUMAN"},
        )
        blocked_human = client.post(
            "/api/v2/cognition/decide",
            json={**decision, "idempotency_key": "runtime-human"},
        )
        replay = client.put(
            runtime_url,
            json={**scope, "runtime_kind": "REPLAY"},
        )
        blocked_replay = client.post(
            "/api/v2/cognition/decide",
            json={**decision, "idempotency_key": "runtime-replay"},
        )
        denied_read = client.get(
            runtime_url,
            headers={"X-TTDM-Actor-ID": outsider["actor_id"]},
            query_string=scope,
        )

    assert absent.status_code == 404
    assert default_decision.status_code == 201
    assert default_decision.get_json()["tier"] == "PLANNER"
    assert default_decision.get_json()["runtime_assignment"] is None
    assert denied.status_code == 403
    assert wrong_run.status_code == 400
    assert local.status_code == 201
    assert loaded.status_code == 200
    assert loaded.get_json()["runtime_kind"] == "LOCAL_LLM"
    assert local_decision.status_code == 201
    assert local_decision.get_json()["runtime_assignment"]["runtime_kind"] == "LOCAL_LLM"
    assert local_decision.get_json()["trace"]["fallback_reason"] == ("model_provider_unavailable")
    assert utility.status_code == 200
    assert utility_decision.status_code == 201
    assert utility_decision.get_json()["tier"] == "UTILITY"
    assert utility_decision.get_json()["trace"]["fallback_reason"] == "llm_disabled"
    assert human.status_code == 200
    assert blocked_human.status_code == 403
    assert replay.status_code == 200
    assert blocked_replay.status_code == 403
    assert denied_read.status_code == 403
