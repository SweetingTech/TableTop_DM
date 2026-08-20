import json
import re
import uuid

import pytest

from kernel.api.app import app, create_app

pytestmark = pytest.mark.unit


def test_built_spa_assets_are_not_swallowed_by_history_fallback():
    with app.test_client() as client:
        index = client.get("/v2/game")
        match = re.search(rb'src="(/static/v2/assets/[^"]+\.js)"', index.data)
        assert match is not None
        asset = client.get(match.group(1).decode())
    assert index.status_code == 200
    assert asset.status_code == 200
    assert asset.mimetype in {"application/javascript", "text/javascript"}
    assert not asset.data.lstrip().startswith(b"<!doctype html")


def test_v2_meta_reports_neutral_contract_and_disabled_telemetry():
    response = app.test_client().get("/api/v2/meta")
    assert response.status_code == 200
    body = response.get_json()
    assert body["contract_version"] == "2.0.0"
    assert body["persona_dimensions"] == 80
    assert body["telemetry_enabled"] is False
    assert body["migrations_from_v1_supported"] is False


def test_tokenless_loopback_rejects_cross_site_and_untrusted_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    local_app = create_app(artifact_root=tmp_path)
    with local_app.test_client() as client:
        same_origin = client.get(
            "/api/v2/meta",
            headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1"},
        )
        cross_origin = client.get(
            "/api/v2/meta",
            headers={"Host": "127.0.0.1", "Origin": "https://evil.example"},
        )
        cross_site = client.get(
            "/api/v2/meta",
            headers={"Host": "localhost", "Sec-Fetch-Site": "cross-site"},
        )
        rebound_host = client.get(
            "/api/v2/meta",
            headers={"Host": "rebound.evil.example"},
        )

    assert same_origin.status_code == 200
    assert cross_origin.status_code == 403
    assert cross_origin.get_json()["error"] == "cross_site_request_rejected"
    assert cross_site.status_code == 403
    assert rebound_host.status_code == 403
    assert rebound_host.get_json()["error"] == "untrusted_loopback_host"


def test_configured_operator_token_allows_explicit_remote_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", "unit-test-operator-token")
    local_app = create_app(artifact_root=tmp_path)
    with local_app.test_client() as client:
        denied = client.get("/api/v2/meta", environ_base={"REMOTE_ADDR": "203.0.113.20"})
        allowed = client.get(
            "/api/v2/meta",
            headers={"X-TTDM-Operator-Token": "unit-test-operator-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.20"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_actor_api_rejects_unledgered_control_claims(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    local_app = create_app(artifact_root=tmp_path)
    with local_app.test_client() as client:
        rejected = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Control forger",
                "controlled_entity_ids": [str(uuid.uuid4())],
            },
        )

    assert rejected.status_code == 400
    assert rejected.get_json()["error"] == "invalid_request"


def test_v2_onboarding_endpoint_runs_seeded_cohort():
    response = app.test_client().post(
        "/api/v2/scenarios/player-onboarding/run",
        json={"cohort_size": 2, "seeds": [101], "include_trials": 2},
    )
    assert response.status_code == 201
    body = response.get_json()["report"]
    assert body["trial_count"] == 2
    assert body["canonical_world_unchanged"] is True


def test_v2_persona_generation_is_seeded():
    request = {
        "seed": 4815162342,
        "fixed": {"player_style": "EXPLORER", "rules_familiarity": "LOW"},
    }
    with app.test_client() as client:
        first = client.post("/api/v2/personas/generate", json=request)
        second = client.post("/api/v2/personas/generate", json=request)
    assert first.status_code == 201
    assert first.get_json() == second.get_json()


def test_v2_calibration_never_auto_promotes():
    response = app.test_client().post(
        "/api/v2/calibration/compare",
        json={
            "synthetic_metrics": {"completion_rate": 0.9},
            "human_metrics": {"completion_rate": 0.75},
            "policy_version": "onboarding-policy-1.0.0",
            "evidence_version": "local-playtests-1",
        },
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["promotion_status"] == "REVIEW_REQUIRED"
    assert body["human_ground_truth_claimed"] is False


def test_v2_cognition_proposes_without_committing_and_retains_trace():
    with app.test_client() as client:
        bootstrap = client.get("/api/v2/bootstrap").get_json()
        persona = client.post(
            "/api/v2/personas/generate", json={"seed": 704, "fixed": {}}
        ).get_json()
        before = client.get(f"/api/v2/worlds/{bootstrap['ids']['world_id']}").get_json()[
            "state_hash"
        ]
        response = client.post(
            "/api/v2/cognition/decide",
            json={
                "persona_id": persona["persona_id"],
                "seed": 55,
                "actor_id": bootstrap["ids"]["actor_id"],
                "embodied_entity_id": bootstrap["ids"]["hero_id"],
                "actions": [
                    {
                        "action": "look",
                        "command_type": "tabletop.console.submit",
                        "parameters": {"text": "I study the old gate."},
                        "utility_factors": {"goal_alignment": 1.0},
                    },
                    {
                        "action": "wait",
                        "command_type": "tabletop.console.submit",
                        "parameters": {"text": "/wait"},
                        "utility_factors": {"goal_alignment": 0.0},
                    },
                ],
            },
        )
        after = client.get(f"/api/v2/worlds/{bootstrap['ids']['world_id']}").get_json()[
            "state_hash"
        ]
        mind = client.get(f"/api/v2/entities/{bootstrap['ids']['hero_id']}/mind").get_json()
    assert response.status_code == 201
    body = response.get_json()
    assert body["committed"] is False
    assert body["proposal"]["decision_trace_id"] == body["trace"]["trace_id"]
    assert body["trace"]["persona_version"] != persona["schema_version"]
    uuid.UUID(body["trace"]["persona_version"])
    assert before == after
    assert mind["decisions"][-1]["trace_id"] == body["trace"]["trace_id"]


def test_v2_console_event_can_become_subjective_memory():
    with app.test_client() as client:
        bootstrap = client.get("/api/v2/bootstrap").get_json()["ids"]
        observer_actor = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Independent witness",
                "kind": "HUMAN",
                "roles": ["OBSERVER"],
                "capabilities": ["world.read.all", "entity.control"],
            },
        ).get_json()
        observer_entity = client.post(
            f"/api/v2/worlds/{bootstrap['world_id']}/entities",
            json={
                "name": "Quay Witness",
                "entity_type": "NPC",
                "controller_actor_id": observer_actor["actor_id"],
                "public_state": {"x": 3, "y": 3},
            },
        ).get_json()
        command = client.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.console.submit",
                "world_id": bootstrap["world_id"],
                "branch_id": bootstrap["branch_id"],
                "run_id": bootstrap["run_id"],
                "actor_id": bootstrap["actor_id"],
                "embodied_entity_id": bootstrap["hero_id"],
                "parameters": {
                    "text": "The bell rang twice.",
                    "claims": [
                        {
                            "subject_type": "location",
                            "predicate": "bell_rang",
                            "value": 2,
                            "confidence": 1,
                        }
                    ],
                },
                "idempotency_key": "subjective-memory-test",
            },
        )
        event = command.get_json()["event"]
        observed = client.post(
            f"/api/v2/events/{event['event_id']}/observe",
            json={
                "observer_actor_id": bootstrap["actor_id"],
                "observer_entity_id": bootstrap["hero_id"],
                "importance": 0.8,
            },
        )
        second_observation = client.post(
            f"/api/v2/events/{event['event_id']}/observe",
            json={
                "observer_actor_id": observer_actor["actor_id"],
                "observer_entity_id": observer_entity["entity_id"],
                "acuity": 0.4,
                "importance": 0.5,
            },
        )
    assert command.status_code == 200
    assert event["observed_by"] == []
    assert observed.status_code == 201
    assert observed.get_json()["memory"]["summary"]
    assert second_observation.status_code == 201
    first_belief = observed.get_json()["belief_revision"]["active_beliefs"][0]
    second_belief = second_observation.get_json()["belief_revision"]["active_beliefs"][0]
    assert first_belief["value"] == second_belief["value"] == 2
    assert first_belief["confidence"] == 1
    assert second_belief["confidence"] == 0.4


def test_v2_population_aliases_support_sampling_and_lazy_activation():
    with app.test_client() as client:
        created = client.post(
            "/api/v2/populations/generate",
            json={"name": "API lifecycle test", "size": 20, "seed": 3301},
        )
        population = created.get_json()
        sampled = client.post(
            f"/api/v2/populations/{population['population_id']}/sample",
            json={"strata": [], "per_cell": 3, "seed": 9},
        ).get_json()
        materialized = client.post(
            f"/api/v2/populations/{population['population_id']}/materialize",
            json={"count": 3},
        ).get_json()
        active = client.post(
            f"/api/v2/populations/{population['population_id']}/activate",
            json={"count": 2},
        ).get_json()
    assert created.status_code == 201
    assert len(sampled["items"]) == 3
    assert set(sampled["items"][0]) == {"persona_id", "seed", "dimensions"}
    assert materialized["materialized"] == 3
    assert active["active"] == 2
    assert materialized["world_id"] == active["world_id"] == population["world_id"]
    assert materialized["branch_id"] == active["branch_id"] == population["branch_id"]


def test_v2_entity_creation_crosses_the_typed_ledger_boundary():
    with app.test_client() as client:
        world = client.post(
            "/api/v2/worlds", json={"name": f"Entity ledger {uuid.uuid4().hex[:8]}"}
        ).get_json()
        before = client.get(f"/api/v2/worlds/{world['world_id']}").get_json()
        created = client.post(
            f"/api/v2/worlds/{world['world_id']}/entities",
            json={
                "name": "Ledger Witness",
                "entity_type": "NPC",
                "public_state": {"x": 4, "y": 7},
                "secret_state": {"hidden_agenda": "never cross a public boundary"},
            },
        )
        after = client.get(f"/api/v2/worlds/{world['world_id']}").get_json()
        listed = client.get(f"/api/v2/worlds/{world['world_id']}/entities").get_json()
        events = client.get(f"/api/v2/events?world_id={world['world_id']}").get_json()

    assert created.status_code == 201
    body = created.get_json()
    assert after["projection_version"] == before["projection_version"] + 1
    assert after["state_hash"] != before["state_hash"]
    assert "secret_state" not in body
    assert all("secret_state" not in entity for entity in listed)
    assert [event["event_id"] for event in events] == [body["creation_event_id"]]
    assert events[0]["event_type"] == "tabletop.entity.spawn"
    assert "hidden_agenda" not in json.dumps(events)


def test_v2_promotes_only_reviewed_trial_consequences_to_canonical_state():
    with app.test_client() as client:
        world = client.post(
            "/api/v2/worlds", json={"name": f"Promotion {uuid.uuid4().hex[:8]}"}
        ).get_json()
        world_id = world["world_id"]
        canonical_id = world["canonical_branch_id"]
        before = client.get(f"/api/v2/worlds/{world_id}").get_json()
        snapshot = client.post(f"/api/v2/worlds/{world_id}/snapshots").get_json()
        trial = client.post(
            f"/api/v2/snapshots/{snapshot['snapshot_id']}/branches",
            json={"world_id": world_id, "seed": 8128},
        ).get_json()
        package = {
            "source_branch_id": trial["branch_id"],
            "expected_canonical_hash": before["state_hash"],
            "deltas": [
                {
                    "projection": "tabletop.reputation",
                    "operation": "MERGE",
                    "values": {"reviewed_trial_effect": 1},
                }
            ],
            "review_note": "GM reviewed the isolated trial ledger.",
        }
        promoted = client.post(f"/api/v2/branches/{canonical_id}/promotions", json=package)
        after = client.get(f"/api/v2/worlds/{world_id}").get_json()

    assert promoted.status_code == 201
    assert promoted.get_json()["result"]["result"]["promoted_delta_count"] == 1
    assert after["projections"]["tabletop.reputation"]["singleton"] == {"reviewed_trial_effect": 1}
    assert after["state_hash"] != before["state_hash"]


def test_v2_telemetry_is_opt_in_redacted_exportable_and_deletable():
    with app.test_client() as client:
        disabled = client.post(
            "/api/v2/telemetry/events",
            json={"event_type": "ui.action", "payload": {"password": "nope"}},
        )
        settings = client.put("/api/v2/telemetry", json={"enabled": True, "retention_days": 7})
        captured = client.post(
            "/api/v2/telemetry/events",
            json={
                "event_type": "ui.action",
                "payload": {"screen": "scenario", "password": "never-store"},
                "consent_version": "test-consent-2026-01",
            },
        )
        exported = client.get("/api/v2/telemetry/export").get_json()
        imported = client.post(
            "/api/v2/telemetry/import",
            json={"events": [{"event_type": "human.playtest", "payload": {"ok": True}}]},
        )
        deleted = client.delete("/api/v2/telemetry/events")
        client.put("/api/v2/telemetry", json={"enabled": False})
    assert disabled.status_code == 403
    assert settings.get_json()["retention_days"] == 7
    assert captured.status_code == 201
    assert captured.get_json()["payload"]["password"] == "[REDACTED]"
    assert exported[-1]["payload"]["password"] == "[REDACTED]"
    assert imported.get_json()["imported"] == 1
    assert deleted.get_json()["deleted"] >= 2
