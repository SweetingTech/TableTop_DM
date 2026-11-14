from __future__ import annotations

import os
import secrets
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.control import ControllerState
from kernel.database import transaction
from kernel.errors import AuthorizationDenied
from kernel.event_factory import EventFactory
from tests.unit.kernel.test_speech_combat_behavior import prompt, provoke, setup_scene

pytestmark = pytest.mark.integration


def prepare(stack, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    scope = admin.post("/api/v2/worlds", json={"name": "Choice " + uuid.uuid4().hex}).get_json()
    return app, setup_scene(app, scope=scope)


@pytest.fixture(autouse=True)
def drain(integration_stack):
    yield
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_speech_history_clock_ties_restart_and_unattended_reply(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    original = EventFactory.materialize
    instant = datetime.now(UTC)

    def tied(self, **kwargs):
        result = original(self, **kwargs)
        return result.model_copy(
            update={"event": result.event.model_copy(update={"created_at": instant})}
        )

    monkeypatch.setattr(EventFactory, "materialize", tied)
    for index in range(4):
        prompt(admin, base, target, f"prompt-{index}")
        body = {
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "Hello friend.", "volume": "WHISPER"},
            "idempotency_key": f"human-{index}",
        }
        first = player.post("/api/v2/commands", json=body)
        assert first.status_code == 200, first.get_json()
        assert player.post("/api/v2/commands", json=body).get_json() == first.get_json()
    prompt(admin, base, target, "new-prompt")
    before = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert before["comparable_count"] == 4
    advice = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "speech"}
    )
    assert advice.status_code == 200, advice.get_json()
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert restored.get(path + "/choice-profile", query_string={"run_id": run}).get_json() == before
    assert (
        restored.post(
            path + "/character-proposals", json={"run_id": run, "idempotency_key": "speech"}
        ).get_json()
        == advice.get_json()
    )
    assert (
        restored.post(
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
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT parameters FROM sim.command_log WHERE run_id=%s "
            "AND decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        parameters = cursor.fetchone()[0]
        assert parameters["volume"] == "WHISPER" and parameters["text"] == "Hello. Good to see you."
        cursor.execute(
            "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 4


def test_combat_history_executes_and_stale_takeover_cannot_commit(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    provoke(admin, base, target, card, "provoked")
    for index in range(4):
        response = player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.combat.attack",
                "parameters": {"target_id": target},
                "seed": 2,
                "idempotency_key": f"human-{index}",
            },
        )
        assert response.status_code == 200, response.get_json()
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 2,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    worker = create_app(artifact_root=tmp_path)
    assert worker.extensions["character_runner"].run_once() == 1
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT parameters FROM sim.command_log WHERE run_id=%s "
            "AND decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        assert cursor.fetchone()[0]["target_id"] == target
        cursor.execute(
            "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 4
    state = ControllerState.model_validate(
        player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    )
    pending = worker.extensions["character_decisions"].decide(
        state.scope, state.executor_actor_id, f"controller:{state.epoch}:step:{state.step}", state
    )
    assert (
        player.post(
            path + "/control",
            json={"run_id": run, "mode": "HUMAN", "expected_epoch": 1, "idempotency_key": "take"},
        ).status_code
        == 200
    )
    assert worker.extensions["character_runner"].run_once() == 0
    with pytest.raises(AuthorizationDenied):
        worker.extensions["simulation"].submit(pending.outcome.proposal)


def test_choice_evidence_failure_rolls_back_action_and_private_rls(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    prompt(admin, base, target, "prompt")
    repository = app.extensions["simulation"].durable_repository
    original = repository.evidence_persister

    def fail(*args):
        raise RuntimeError("test choice storage failure")

    repository.evidence_persister = fail
    body = {
        **base,
        "embodied_entity_id": card["entity_id"],
        "command_type": "tabletop.dialogue.speak",
        "parameters": {"text": "Hello."},
        "idempotency_key": "reply",
    }
    response = player.post("/api/v2/commands", json=body)
    assert response.status_code == 500
    repository.evidence_persister = original
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE run_id=%s AND idempotency_key='reply'",
            (run,),
        )
        assert cursor.fetchone()[0] == 0
    good = player.post("/api/v2/commands", json=body)
    assert good.status_code == 200, good.get_json()
    assert player.post("/api/v2/commands", json=body).get_json() == good.get_json()
    with (
        transaction(actor_id=uuid.uuid4(), dsn=integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 0
    owner = uuid.UUID(
        player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()[
            "player_actor_id"
        ]
    )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with (
            transaction(actor_id=owner, dsn=integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM cognition.human_choice_evidence WHERE run_id=%s", (run,))
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE cognition.human_choice_evidence SET payload=payload WHERE run_id=%s", (run,)
            )


def test_upgrade_from008_is_repeatable(integration_stack, tmp_path):
    name = "ttdm_choice_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:8]:
            shutil.copy2(path, prior / path.name)
        assert migrate(url, prior) == 8
        assert migrate(url, migrations) == 2
        assert migrate(url, migrations) == 0
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        maintenance.close()


def test_choice_source_payload_and_binding_constraints(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    prompt(admin, base, target, "prompt")
    body = {
        **base,
        "embodied_entity_id": card["entity_id"],
        "command_type": "tabletop.dialogue.speak",
        "parameters": {"text": "Hello."},
        "idempotency_key": "human",
    }
    assert player.post("/api/v2/commands", json=body).status_code == 200
    columns = (
        "event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
        "character_id,binding_id,payload"
    )
    selected = (
        "event_id,world_id,branch_id,run_id,entity_id,player_actor_id,character_id,binding_id,"
    )
    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_choice_evidence ("
                + columns
                + ") SELECT "
                + selected
                + "jsonb_set(payload,'{projection_version}','-1') "
                "FROM cognition.human_choice_evidence WHERE run_id=%s",
                (run,),
            )
    with pytest.raises(psycopg2.errors.RaiseException, match="absent"):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_choice_evidence ("
                + columns
                + ") SELECT "
                + selected
                + "jsonb_set(payload,'{options}','[]') "
                "FROM cognition.human_choice_evidence WHERE run_id=%s",
                (run,),
            )
    with pytest.raises(psycopg2.errors.RaiseException, match="matching committed"):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_choice_evidence (" + columns + ") "
                "SELECT %s,world_id,branch_id,run_id,entity_id,player_actor_id,"
                "character_id,binding_id,payload "
                "FROM cognition.human_choice_evidence WHERE run_id=%s",
                (str(uuid.uuid4()), run),
            )
    prompt(admin, base, target, "newprompt")
    repository = app.extensions["simulation"].durable_repository
    original = repository.evidence_builder
    repository.evidence_builder = None
    try:
        response = player.post("/api/v2/commands", json={**body, "idempotency_key": "no-sample"})
        assert response.status_code == 200
    finally:
        repository.evidence_builder = original
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            foreign = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO cognition.human_choice_evidence (" + columns + ") "
                "SELECT %s,world_id,branch_id,run_id,entity_id,player_actor_id,character_id,%s,"
                "jsonb_set(payload,'{binding_id}',to_jsonb(%s::text)) "
                "FROM cognition.human_choice_evidence WHERE run_id=%s",
                (response.get_json()["event"]["event_id"], foreign, foreign, run),
            )
