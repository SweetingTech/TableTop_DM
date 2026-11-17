from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_world_time import api_command, clock_game

pytestmark = pytest.mark.unit


def seed_routine(app, admin, base, target, *, bind=True):
    clock_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"
    activity = admin.get(clock_path).get_json()["activities"].get(target)
    if activity is not None:
        api_command(
            admin,
            base,
            "tabletop.activity.cancel",
            {"entity_id": target, "activity_id": activity["activity_id"]},
            "cancel-manual",
        )
    response = admin.post(
        "/api/v2/populations/generate",
        json={
            "name": "Living village",
            "size": 4,
            "seed": int(uuid.uuid4().hex[:6], 16),
            "world_id": base["world_id"],
            "branch_id": base["branch_id"],
        },
    )
    assert response.status_code == 201, response.get_json()
    pool = response.get_json()["population_id"]
    root = f"/api/v2/populations/{pool}"
    sampled = admin.post(
        root + "/sample", json={"strata": [], "per_cell": 1, "seed": 1}
    ).get_json()["items"][0]
    persona = sampled["persona_id"]
    member_path = root + f"/members/{persona}"
    response = admin.post(
        root + "/materialize",
        json={
            "persona_id": persona,
            "profile": sampled["dimensions"],
            "world_step": 17,
            "persistent_state": {
                "finances": {"coins": 999},
                "memories": ["PRIVATE_GARDEN_HISTORY"],
            },
        },
    )
    assert response.status_code == 201, response.get_json()
    bind_body = {
        "entity_id": target,
        "run_id": base["run_id"],
        "expected_source_version": 1,
        "idempotency_key": "bind-member",
    }
    if not bind:
        return root, member_path, bind_body
    response = admin.post(member_path + "/bind", json=bind_body)
    assert response.status_code == 200, response.get_json()
    api_command(
        admin,
        base,
        "tabletop.routine.configure",
        {
            "entity_id": target,
            "expected_version": 0,
            "work_seconds": 120,
            "rest_seconds": 60,
            "hunger_limit": 300,
            "fatigue_limit": 180,
        },
        "routine",
    )
    return root, member_path, bind_body


def test_live_member_reads_counts_and_legacy_transitions_use_canonical_lifecycle(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    root, member_path, bind_body = seed_routine(app, admin, base, target)
    assert admin.post(member_path + "/bind", json=bind_body).status_code == 200
    member = admin.get(member_path)
    assert member.headers["Cache-Control"] == "no-store"
    assert member.get_json()["entity_id"] == target
    assert "finances" not in member.get_json()["persistent_state"]
    for action, expected in (("activate", "ACTIVE"), ("deactivate", "MATERIALIZED")):
        response = admin.post(
            member_path + "/" + action,
            json={"active_state": {}, "world_step": 100}
            if action == "activate"
            else {"world_step": 101},
        )
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["level"] == expected
        pools = admin.get("/api/v2/populations").get_json()
        pool = next(item for item in pools if root.endswith(item["population_id"]))
        assert pool["active"] == (1 if expected == "ACTIVE" else 0)
    assert (
        admin.post(
            member_path + "/activate",
            json={"active_state": {"finances": {"coins": 9999}}, "world_step": 102},
        ).status_code
        == 400
    )
    response = admin.post(root + "/activate", json={"count": 1})
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["active"] == 1
    assert admin.get(member_path).get_json()["level"] == "ACTIVE"
    history = admin.get(root + "/transitions").get_json()
    assert [item["lifecycle_version"] for item in history] == [1, 2, 3, 4, 5]


def test_player_sees_physical_work_but_no_population_identity_or_routine_internals(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    root, member_path, bind_body = seed_routine(app, admin, base, target)
    runtime_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/population"
    assert admin.get(runtime_path).headers["Cache-Control"] == "no-store"
    assert player.get(runtime_path).status_code == 403
    assert player.get(member_path).status_code == 403
    forbidden = player.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.routine.configure",
            "parameters": {"entity_id": target, "expected_version": 1},
            "idempotency_key": "forbidden-routine",
        },
    )
    assert forbidden.status_code == 403
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 30},
        "thirty",
    )
    scene = player.get(path + "/scene").get_json()
    entity = next(row for row in scene["perceived_entities"] if row["entity_id"] == target)
    assert entity["activity"]["weeded_units"] == 30
    for private in (
        "PRIVATE_GARDEN_HISTORY",
        "population_id",
        "routine_id",
        "phase_sequence",
        "source_hash",
        "policy_version",
        "bound_at_seconds",
        "MATERIALIZED",
    ):
        assert private not in str(scene)
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200, context.get_json()
    for private in (
        "PRIVATE_GARDEN_HISTORY",
        "population_id",
        "routine_id",
        "phase_sequence",
        "source_hash",
        "bound_at_seconds",
        "MATERIALIZED",
    ):
        assert private not in str(context.get_json())
