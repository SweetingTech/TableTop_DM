from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.database import transaction
from kernel.errors import AuthorizationDenied
from kernel.postgres_repository import PostgresCommandRepository
from tests.integration.test_clean_boot import _stop_runtime
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def delivered_controller_outbox(integration_stack):
    yield
    # These tests exercise the actual outbox acknowledgement too, so later
    # integration tests don't inherit an unbounded pending delivery backlog.
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def setup(integration_stack, monkeypatch, tmp_path):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = token
    scope = admin.post("/api/v2/worlds", json={"name": "Runner " + uuid.uuid4().hex}).get_json()
    return app, setup_bound_character(app, token, scope=scope)


def test_durable_handoff_unattended_commit_restart_and_takeover(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    request = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "AUTONOMOUS",
        "max_steps": 1,
        "interval_ms": 100,
        "idempotency_key": "leave",
    }
    response = player.post(path + "/control", json=request)
    assert response.status_code == 200, response.get_json()
    assert player.post(path + "/control", json=request).get_json() == response.get_json()
    state = response.get_json()["state"]
    runtime_path = f"/api/v2/entities/{card['entity_id']}/runtime"
    runtime_scope = {"world_id": card["world_id"], "branch_id": state["branch_id"], "run_id": run}
    runtime = player.get(runtime_path, query_string=runtime_scope).get_json()
    assert runtime["runtime_kind"] == "UTILITY" and runtime["controller"]["epoch"] == 1
    before_scene = player.get(path + "/scene").get_json()
    # The runner is a separate application and never uses the player's cookie.
    worker = create_app(artifact_root=tmp_path)
    due = worker.extensions["controllers"].due()
    assert len(due) == 1
    planned = worker.extensions["character_decisions"].decide(
        due[0].scope,
        due[0].executor_actor_id,
        f"controller:{due[0].epoch}:step:{due[0].step}",
        due[0],
    )
    assert planned.outcome.proposal.decision_authorship == "CHARACTER_POLICY"
    assert worker.extensions["character_runner"].run_once() == 1
    assert worker.extensions["character_runner"].run_once() == 0
    refreshed = player.get(path + "/scene").get_json()
    assert refreshed["projection_version"] == before_scene["projection_version"] + 1
    self_view = next(
        entity
        for entity in refreshed["perceived_entities"]
        if entity["entity_id"] == card["entity_id"]
    )
    assert self_view["position"]["x"] == planned.outcome.proposal.parameters["dx"]
    assert self_view["position"]["y"] == planned.outcome.proposal.parameters["dy"]
    assert (
        player.get(path + "/context", query_string={"run_id": run}).get_json()["projection_version"]
        == refreshed["projection_version"]
    )
    current = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert current["mode"] == "PAUSED" and current["step"] == 1
    assert current["owner_actor_id"] != current["executor_actor_id"]
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert (
        restored.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
        == current
    )
    taken = restored.post(
        path + "/control",
        json={**request, "mode": "HUMAN", "expected_epoch": 1, "idempotency_key": "return"},
    )
    assert taken.status_code == 200, taken.get_json()
    assert (
        restored.get(runtime_path, query_string=runtime_scope).get_json()["runtime_kind"] == "HUMAN"
    )
    action = {
        "command_type": "tabletop.spatial.move",
        "world_id": card["world_id"],
        "branch_id": current["branch_id"],
        "run_id": run,
        "embodied_entity_id": card["entity_id"],
        "parameters": {"dx": 1, "dy": 0},
        "idempotency_key": "returned-human",
        "control_epoch": 2,
    }
    result = restored.post("/api/v2/commands", json=action)
    assert result.status_code == 200, result.get_json()


def test_two_workers_and_takeover_fence_one_logical_action(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    request = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "AUTONOMOUS",
        "max_steps": 1,
        "interval_ms": 100,
        "idempotency_key": "leave",
    }
    assert player.post(path + "/control", json=request).status_code == 200
    workers = [create_app(artifact_root=tmp_path) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda worker: worker.extensions["character_runner"].run_once(), workers))
    state = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert state["step"] == 1
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE run_id=%s AND "
            "decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT count(*) FROM sim.events WHERE run_id=%s AND event_type LIKE '%%control%%'",
            (run,),
        )
        assert cursor.fetchone()[0] == 0
    resumed = player.post(
        path + "/control", json={**request, "expected_epoch": 1, "idempotency_key": "resume"}
    )
    assert resumed.status_code == 200
    worker = create_app(artifact_root=tmp_path)
    controller = next(
        row for row in worker.extensions["controllers"].due() if str(row.run_id) == run
    )
    receipt = worker.extensions["character_decisions"].decide(
        controller.scope,
        controller.executor_actor_id,
        f"controller:{controller.epoch}:step:0",
        controller,
    )
    assert (
        player.post(
            path + "/control",
            json={**request, "expected_epoch": 2, "mode": "HUMAN", "idempotency_key": "take"},
        ).status_code
        == 200
    )
    with pytest.raises(AuthorizationDenied):
        worker.extensions["character_runner"].snapshot().submit(receipt.outcome.proposal)
    assert (
        player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]["step"]
        == 0
    )


def test_private_control_rls_grants_and_handoff_rollback(integration_stack, monkeypatch, tmp_path):
    app, (_, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    request = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "AUTONOMOUS",
        "idempotency_key": "leave",
        "max_steps": 3,
    }
    assert player.post(path + "/control", json=request).status_code == 200
    state = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    owner, executor = map(uuid.UUID, [state["owner_actor_id"], state["executor_actor_id"]])
    for actor, expected in [(owner, 1), (executor, 1), (uuid.uuid4(), 0), (None, 0)]:
        with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM cognition.controller_assignments WHERE entity_id=%s",
                    (card["entity_id"],),
                )
                assert cursor.fetchone()[0] == expected
    with transaction(actor_id=executor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM tabletop.character_card_revisions WHERE character_id=%s",
                (card["character_id"],),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT count(*) FROM cognition.mind_states WHERE entity_id=%s",
                (card["entity_id"],),
            )
            assert cursor.fetchone()[0] == 1
    for field, value in [("epoch", 99), ("max_steps", 1000), ("mode", "HUMAN")]:
        with pytest.raises(psycopg2.errors.RaiseException):
            with transaction(actor_id=executor, dsn=integration_stack.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE cognition.controller_assignments SET payload="
                        "jsonb_set(payload,%s,%s::jsonb) WHERE entity_id=%s",
                        ([field], json.dumps(value), card["entity_id"]),
                    )
    # Fail after changing the controller but before its append-only receipt is saved.
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "CREATE FUNCTION cognition.fail_handoff_test() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$"
        )
        cursor.execute(
            "CREATE TRIGGER fail_handoff_test BEFORE INSERT ON cognition.controller_handoffs "
            "FOR EACH ROW EXECUTE FUNCTION cognition.fail_handoff_test()"
        )
    try:
        failed = player.post(
            path + "/control",
            json={**request, "expected_epoch": 1, "mode": "HUMAN", "idempotency_key": "rollback"},
        )
        assert failed.status_code == 400
        assert "injected failure" not in failed.get_data(as_text=True)
        assert (
            player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
            == state
        )
    finally:
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("DROP TRIGGER fail_handoff_test ON cognition.controller_handoffs")
            cursor.execute("DROP FUNCTION cognition.fail_handoff_test()")
    assert (
        player.post(
            path + "/control",
            json={**request, "expected_epoch": 1, "mode": "HUMAN", "idempotency_key": "take"},
        ).status_code
        == 200
    )
    with transaction(actor_id=executor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM tabletop.character_card_revisions WHERE character_id=%s",
                (card["character_id"],),
            )
            assert cursor.fetchone()[0] == 0
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with transaction(actor_id=owner, dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM cognition.controller_handoffs WHERE run_id=%s", (run,))
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE cognition.controller_handoffs SET idempotency_key='rewrite' "
                "WHERE run_id=%s",
                (run,),
            )


def test_upgrade_from_006_is_idempotent(integration_stack, tmp_path):
    name = "ttdm_control_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:6]:
            shutil.copy2(path, prior / path.name)
        assert migrate(url, prior) == 6
        assert migrate(url, migrations) == 4
        assert migrate(url, migrations) == 0
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (name,)
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        maintenance.close()


def test_real_runner_process_acts_without_player_and_stays_stopped_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    request = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "AUTONOMOUS",
        "max_steps": 1,
        "interval_ms": 100,
        "idempotency_key": "leave-process",
    }
    assert player.post(path + "/control", json=request).status_code == 200
    environment = os.environ.copy()
    environment["TTDM_ARTIFACT_ROOT"] = str(tmp_path)
    environment.pop("QDRANT_URL", None)
    for attempt in range(2):
        output = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "main.py", "runner"],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        process.runtime_output = output
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                state = player.get(path + "/control", query_string={"run_id": run}).get_json()[
                    "control"
                ]
                if state["step"] == 1:
                    break
                assert process.poll() is None, (
                    "runner exited before processing an enabled character"
                )
                time.sleep(0.1)
            assert state["step"] == 1 and state["mode"] == "PAUSED"
            if attempt:
                time.sleep(0.4)
                assert (
                    player.get(path + "/control", query_string={"run_id": run}).get_json()[
                        "control"
                    ]["step"]
                    == 1
                )
        finally:
            _stop_runtime(process)


def test_service_action_projects_for_unowned_npc_witness(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    npc = admin.post(
        f"/api/v2/worlds/{card['world_id']}/entities",
        json={"name": "Working gardener", "entity_type": "NPC", "public_state": {"x": 1, "y": 1}},
    ).get_json()
    assert "entity_id" in npc
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "expected_epoch": 0,
            "mode": "AUTONOMOUS",
            "max_steps": 1,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200
    assert app.extensions["character_runner"].run_once() == 1
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    state = response.get_json()["state"]
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT event_id FROM sim.events WHERE run_id=%s AND actor_id=%s",
            (run, state["executor_actor_id"]),
        )
        event = cursor.fetchone()[0]
        cursor.execute(
            "SELECT controller_actor_id FROM sim.event_perceptions "
            "WHERE event_id=%s AND observer_entity_id=%s",
            (event, card["entity_id"]),
        )
        assert str(cursor.fetchone()[0]) == state["owner_actor_id"]
        cursor.execute(
            "SELECT count(*) FROM cognition.observations "
            "WHERE source_event_id=%s AND observer_entity_id=%s",
            (event, npc["entity_id"]),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT published_at IS NOT NULL FROM sim.outbox WHERE event_id=%s", (event,)
        )
        assert cursor.fetchone()[0] is True


def test_controller_payload_constraints_and_exclusive_handoff_race(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    request = {"run_id": run, "expected_epoch": 0, "mode": "AUTONOMOUS", "idempotency_key": "leave"}
    assert player.post(path + "/control", json=request).status_code == 200
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(c) FROM cognition.controller_assignments c WHERE entity_id=%s",
            (card["entity_id"],),
        )
        row = cursor.fetchone()[0]
        cursor.execute(
            "SELECT row_to_json(h) FROM cognition.controller_handoffs h WHERE entity_id=%s",
            (card["entity_id"],),
        )
        handoff = cursor.fetchone()[0]
    changes = [
        ("world_id", str(uuid.uuid4())),
        ("branch_id", str(uuid.uuid4())),
        ("run_id", str(uuid.uuid4())),
        ("entity_id", str(uuid.uuid4())),
        ("owner_actor_id", str(uuid.uuid4())),
        ("executor_actor_id", str(uuid.uuid4())),
        ("mode", "INVALID"),
        ("epoch", 0),
        ("step", -1),
        ("step", 2000),
        ("max_steps", 0),
        ("max_steps", 1001),
        ("interval_ms", 99),
        ("interval_ms", 60001),
        ("failures", -1),
        ("next_due", None),
    ]
    for field, value in changes:
        data = {**row, "payload": {**row["payload"], field: value}}
        with pytest.raises(psycopg2.errors.CheckViolation):
            with (
                psycopg2.connect(integration_stack.admin_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO cognition.controller_assignments SELECT * FROM "
                    "jsonb_populate_record(NULL::cognition.controller_assignments,%s::jsonb)",
                    (json.dumps(data),),
                )
    for field, value in [
        ("actor_id", str(uuid.uuid4())),
        ("idempotency_key", "forged"),
        ("sensory_event", True),
        ("state", {}),
    ]:
        data = {**handoff, "payload": {**handoff["payload"], field: value}}
        with pytest.raises(psycopg2.errors.CheckViolation):
            with (
                psycopg2.connect(integration_stack.admin_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO cognition.controller_handoffs SELECT * FROM "
                    "jsonb_populate_record(NULL::cognition.controller_handoffs,%s::jsonb)",
                    (json.dumps(data),),
                )
    cookie = player.get_cookie("ttdm_session").value

    def compete(index):
        client = app.test_client()
        client.set_cookie("ttdm_session", cookie)
        return client.post(
            path + "/control",
            json={
                **request,
                "expected_epoch": 1,
                "mode": "HUMAN",
                "idempotency_key": f"take-{index}",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(compete, range(2))) == [200, 409]


def test_controller_step_rolls_back_with_failed_canonical_commit(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "expected_epoch": 0,
                "mode": "AUTONOMOUS",
                "max_steps": 1,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    worker = app.extensions["character_runner"]
    state = next(row for row in app.extensions["controllers"].due() if str(row.run_id) == run)
    receipt = worker.decisions.decide(
        state.scope, state.executor_actor_id, f"controller:{state.epoch}:step:0", state
    )

    def fail(*args):
        raise RuntimeError("injected event persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        with pytest.raises(RuntimeError, match="injected"):
            worker.snapshot().submit(receipt.outcome.proposal)
    assert (
        player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]["step"]
        == 0
    )
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE run_id=%s "
            "AND decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        assert cursor.fetchone()[0] == 0
    original = worker.snapshot().submit(receipt.outcome.proposal)
    retry = worker.snapshot().submit(receipt.outcome.proposal)
    assert original == retry
    assert (
        player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]["step"]
        == 1
    )
