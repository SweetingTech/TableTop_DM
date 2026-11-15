from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests.integration.test_relationship_snapshot_repairs import fresh_client, snapshot
from tests.integration.test_world_time import prepare

pytestmark = pytest.mark.integration


def test_generic_scenarios_restore_populated_entities_and_replay_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base = game[0], game[-1]
    world = uuid.UUID(base["world_id"])
    canonical_id = uuid.UUID(base["branch_id"])
    simulation = app.extensions["simulation"]
    manifest = snapshot(admin, str(world))
    frozen = simulation.snapshot_store.load(
        simulation.snapshots[uuid.UUID(manifest["snapshot_id"])]
    )
    assert frozen["entities"]
    canonical_hash = manifest["state_hash"]
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sim.entities SET secret_state=%s::jsonb WHERE world_id=%s AND branch_id=%s",
            ('{"future":"not learned"}', str(world), str(canonical_id)),
        )
    scenario_id = "frozen-scenario-" + uuid.uuid4().hex
    definition = {
        "scenario_id": scenario_id,
        "version": "1.0.0",
        "base_snapshot_id": manifest["snapshot_id"],
        "cohort_size": 2,
        "seeds": [17],
        "intervention": {
            "deltas": [
                {
                    "projection": "tabletop.economy",
                    "operation": "SET",
                    "values": {"tax_percent": 15},
                }
            ]
        },
    }
    assert admin.post("/api/v2/scenarios", json=definition).status_code == 201
    request = {"cohort_size": 2, "seeds": [17], "include_trials": 2}
    launched = admin.post(f"/api/v2/scenarios/{scenario_id}/run", json=request)
    assert launched.status_code == 201, launched.get_json()
    payload = launched.get_json()
    assert payload["job"]["status"] == "COMPLETED", payload
    assert payload["report"]["canonical_world_unchanged"]
    trials = payload["report"]["sample_trials"]
    assert len(trials) == 2 and trials[0]["branch_id"] != trials[1]["branch_id"]
    restored_app, reader = fresh_client(tmp_path)
    restored = restored_app.extensions["simulation"]
    assert restored.states.get(canonical_id).state_hash == canonical_hash
    for trial in trials:
        branch_id = uuid.UUID(trial["branch_id"])
        assert trial["status"] == "COMPLETED"
        assert restored.branch_snapshot_ids[branch_id] == uuid.UUID(manifest["snapshot_id"])
        for key, metadata in frozen["entities"].items():
            entity = restored.entities[(branch_id, uuid.UUID(key))]
            assert entity.secret_state == metadata["secret_state"]
            assert str(entity.controller_actor_id) == str(metadata["controller_actor_id"])
            assert entity.name == frozen["projections"]["tabletop.entities"][key]["name"]
        assert restored.states.get(branch_id).projections["tabletop.economy"]["singleton"] == {
            "tax_percent": 15
        }
        replay = reader.get(f"/api/v2/branches/{branch_id}/replay")
        assert replay.status_code == 200 and replay.get_json()["verified"]
    retried = reader.post(f"/api/v2/scenarios/{scenario_id}/run", json=request)
    assert retried.status_code == 201 and retried.get_json()["report_id"] == payload["report_id"]
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, started_at, completed_at FROM experiments.trials "
            "WHERE id=ANY(%s::uuid[])",
            ([trial["trial_id"] for trial in trials],),
        )
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert all(status == "COMPLETED" and started <= ended for status, started, ended in rows)


def test_failed_scenario_records_original_error_without_masking_it_with_timestamp_constraint(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base = game[0], game[-1]
    manifest = snapshot(admin, base["world_id"])
    scenario_id = "invalid-scenario-" + uuid.uuid4().hex
    definition = {
        "scenario_id": scenario_id,
        "version": "1.0.0",
        "base_snapshot_id": manifest["snapshot_id"],
        "cohort_size": 1,
        "seeds": [23],
        "intervention": {"deltas": [{"projection": "tabletop.economy", "operation": "BOGUS"}]},
    }
    assert admin.post("/api/v2/scenarios", json=definition).status_code == 201
    response = admin.post(f"/api/v2/scenarios/{scenario_id}/run", json={})
    assert response.status_code == 400
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT t.status,t.failure_code,t.started_at,t.completed_at "
            "FROM experiments.trials t JOIN experiments.scenarios s ON s.id=t.scenario_id "
            "WHERE s.scenario_key=%s",
            (scenario_id,),
        )
        status, failure, started, ended = cursor.fetchone()
        assert status == "FAILED" and failure == "ValidationError" and started <= ended
    assert (
        app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"])).state_hash
        == (manifest["state_hash"])
    )
