from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.database import transaction
from tests.integration.test_controller_runner import setup
from tests.unit.kernel.test_character_binding_api import setup_bound_character
from tests.unit.kernel.test_player_behavior import movement

pytestmark = pytest.mark.integration


def prepare(integration_stack, monkeypatch, tmp_path):
    app, values = setup(integration_stack, monkeypatch, tmp_path)
    admin, player, card, game, path, run, user = values
    card["branch_id"] = path.split("/")[6]
    return app, admin, player, card, path, run


def test_durable_history_survives_restart_and_controls_actual_runner(
    integration_stack, monkeypatch, tmp_path
):
    app, admin, player, card, path, run = prepare(integration_stack, monkeypatch, tmp_path)
    for index in range(4):
        body = movement(card, run, key=f"human-{index}")
        response = player.post("/api/v2/commands", json=body)
        assert response.status_code == 200, response.get_json()
        assert player.post("/api/v2/commands", json=body).get_json() == response.get_json()
    profile = player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()
    assert profile["comparable_count"] == 4
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    advice = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "history"}
    )
    assert advice.status_code == 200, advice.get_json()
    original = advice.get_json()
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert (
        restored.post(
            path + "/character-proposals", json={"run_id": run, "idempotency_key": "history"}
        ).get_json()
        == original
    )
    assert (
        restored.get(path + "/behavior-profile", query_string={"run_id": run}).get_json() == profile
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
    # A new process/application has no player cookie and consumes persisted human evidence.
    worker = create_app(artifact_root=tmp_path)
    assert worker.extensions["character_runner"].run_once() == 1
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM cognition.human_movement_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 4
        cursor.execute(
            "SELECT parameters,input_origin FROM sim.command_log WHERE run_id=%s "
            "AND decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        parameters, origin = cursor.fetchone()
        assert parameters == {"dx": 0, "dy": -1} and origin == "POLICY_ADVICE"
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_evidence_failure_rolls_back_canonical_action_and_retry_trains_once(
    integration_stack, monkeypatch, tmp_path
):
    app, _, player, card, path, run = prepare(integration_stack, monkeypatch, tmp_path)
    owner = (
        app.extensions["simulation"]
        .entities[(uuid.UUID(card["branch_id"]), uuid.UUID(card["entity_id"]))]
        .controller_actor_id
    )
    proposal = CommandProposal.model_validate(
        {**movement(card, run), "actor_id": owner, "input_origin": "HUMAN_INPUT"}
    )
    repository = app.extensions["simulation"].durable_repository
    original = repository.evidence_persister

    def fail(*args):
        raise RuntimeError("test evidence failure")

    repository.evidence_persister = fail
    with pytest.raises(RuntimeError, match="test evidence failure"):
        app.extensions["simulation"].submit(proposal)
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE command_id=%s", (str(proposal.command_id),)
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM cognition.human_movement_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 0
    repository.evidence_persister = original
    first = player.post("/api/v2/commands", json=proposal.model_dump(mode="json"))
    assert first.status_code == 200, first.get_json()
    assert (
        player.post("/api/v2/commands", json=proposal.model_dump(mode="json")).get_json()
        == first.get_json()
    )
    assert (
        player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()[
            "comparable_count"
        ]
        == 1
    )
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_evidence_rls_append_only_payload_and_source_guards(
    integration_stack, monkeypatch, tmp_path
):
    app, admin, player, card, path, run = prepare(integration_stack, monkeypatch, tmp_path)
    response = player.post("/api/v2/commands", json=movement(card, run))
    assert response.status_code == 200, response.get_json()
    profile = player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()
    owner = uuid.UUID(profile["player_actor_id"])
    _, other_player, other_card, _, _, _, _ = setup_bound_character(
        app,
        scope={
            "world_id": card["world_id"],
            "canonical_branch_id": card["branch_id"],
            "current_run_id": run,
        },
    )
    assert (
        other_player.get(path + "/behavior-profile", query_string={"run_id": run}).status_code
        == 403
    )
    other_actor = (
        app.extensions["simulation"]
        .entities[(uuid.UUID(card["branch_id"]), uuid.UUID(other_card["entity_id"]))]
        .controller_actor_id
    )
    with (
        transaction(actor_id=other_actor, dsn=integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT count(*) FROM cognition.human_movement_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 0
    # Missing actor context cannot see even the existence of another player's evidence.
    with (
        transaction(actor_id=uuid.uuid4(), dsn=integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT count(*) FROM cognition.human_movement_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 0
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with (
            transaction(actor_id=owner, dsn=integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM cognition.human_movement_evidence WHERE run_id=%s", (run,))
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE cognition.human_movement_evidence SET payload=payload WHERE run_id=%s",
                (run,),
            )
    # Trigger validates source authorship independently from caller-supplied JSON labels.
    with pytest.raises(psycopg2.errors.RaiseException, match="matching committed human"):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_movement_evidence "
                "(event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
                "character_id,binding_id,payload) "
                "SELECT %s,world_id,branch_id,run_id,entity_id,player_actor_id,"
                "character_id,binding_id,payload "
                "FROM cognition.human_movement_evidence WHERE run_id=%s",
                (str(uuid.uuid4()), run),
            )
    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_movement_evidence "
                "(event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
                "character_id,binding_id,payload) "
                "SELECT event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
                "character_id,binding_id,"
                "jsonb_set(payload,'{chosen}','\"invalid\"') "
                "FROM cognition.human_movement_evidence WHERE run_id=%s",
                (run,),
            )
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_evidence_option_constraints_and_composite_binding(
    integration_stack, monkeypatch, tmp_path
):
    app, _, player, card, path, run = prepare(integration_stack, monkeypatch, tmp_path)
    assert player.post("/api/v2/commands", json=movement(card, run)).status_code == 200
    columns = (
        "event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
        "character_id,binding_id,payload"
    )
    selected = (
        "event_id,world_id,branch_id,run_id,entity_id,player_actor_id,character_id,binding_id,"
    )
    cases = [
        (["projection_version"], "-1"),
        (["world_id"], '"' + str(uuid.uuid4()) + '"'),
        (["frame", "company"], "3"),
        (["frame", "options", "0", "direction"], '"east"'),
        (["frame", "options", "0", "approach"], "2"),
    ]
    for parts, value in cases:
        with pytest.raises((psycopg2.errors.CheckViolation, psycopg2.errors.RaiseException)):
            with (
                psycopg2.connect(integration_stack.admin_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO cognition.human_movement_evidence ("
                    + columns
                    + ") SELECT "
                    + selected
                    + "jsonb_set(payload,%s,%s::jsonb) FROM cognition.human_movement_evidence "
                    "WHERE run_id=%s",
                    (parts, value, run),
                )
    # Create an otherwise eligible source without a sample to isolate the composite FK.
    repository = app.extensions["simulation"].durable_repository
    builder = repository.evidence_builder
    repository.evidence_builder = None
    try:
        result = player.post(
            "/api/v2/commands", json=movement(card, run, key="source-without-sample")
        )
        assert result.status_code == 200
    finally:
        repository.evidence_builder = builder
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            foreign = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO cognition.human_movement_evidence (" + columns + ") "
                "SELECT %s,world_id,branch_id,run_id,entity_id,player_actor_id,character_id,%s,"
                "jsonb_set(payload,'{binding_id}',to_jsonb(%s::text)) "
                "FROM cognition.human_movement_evidence WHERE run_id=%s",
                (result.get_json()["event"]["event_id"], foreign, foreign, run),
            )
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_upgrade_from_007_preserves_old_commands_as_unknown(integration_stack, tmp_path):
    name = "ttdm_behavior_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:7]:
            shutil.copy2(path, prior / path.name)
        assert migrate(url, prior) == 7
        assert migrate(url, migrations) == 3
        assert migrate(url, migrations) == 0
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_default FROM information_schema.columns WHERE table_schema='sim' "
                "AND table_name='command_log' AND column_name='input_origin'"
            )
            assert "UNSPECIFIED" in cursor.fetchone()[0]
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        maintenance.close()
