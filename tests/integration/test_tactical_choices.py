from __future__ import annotations

import secrets
import shutil
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import migrate
from kernel.api.app import create_app
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene
from tests.unit.kernel.test_tactical_choices import command, resources

pytestmark = pytest.mark.integration


def test_guard_history_restart_and_real_worker(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], hp=12, mana=0)
    for index in range(4):
        provoke(admin, base, target, card, f"hit-{index}")
        response = command(player, base, card, "tabletop.combat.guard", {}, f"guard-{index}")
        assert response.status_code == 200, response.get_json()
        assert (
            command(player, base, card, "tabletop.combat.guard", {}, f"guard-{index}").get_json()
            == response.get_json()
        )
    provoke(admin, base, target, card, "final-hit")
    before = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert before["comparable_count"] == 4
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert restored.get(path + "/choice-profile", query_string={"run_id": run}).get_json() == before
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
            "SELECT command_type FROM sim.command_log WHERE run_id=%s "
            "AND decision_authorship='CHARACTER_POLICY'",
            (run,),
        )
        assert cursor.fetchone()[0] == "tabletop.combat.guard"
        cursor.execute(
            "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone()[0] == 4
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
                + "jsonb_set(payload,'{options}',(payload->'options')||"
                "(payload->'options')||(payload->'options')) "
                "FROM cognition.human_choice_evidence WHERE run_id=%s LIMIT 1",
                (run,),
            )
    with pytest.raises(psycopg2.errors.RaiseException, match="matching committed"):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO cognition.human_choice_evidence ("
                + columns
                + ") SELECT "
                + selected
                + "jsonb_set(payload,'{version}','\"speech-combat-behavior-1.0.0\"') "
                "FROM cognition.human_choice_evidence WHERE run_id=%s LIMIT 1",
                (run,),
            )


def test_spell_evidence_failure_rolls_back_resources_then_retry_once(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"])
    provoke(admin, base, target, card, "hit")
    repository = app.extensions["simulation"].durable_repository
    original = repository.evidence_persister

    def fail(cursor, event, bundle):
        original(cursor, event, bundle)
        raise RuntimeError("test evidence rollback")

    repository.evidence_persister = fail
    parameters = {"spell_id": "MEND", "target_id": card["entity_id"]}
    try:
        assert (
            command(player, base, card, "tabletop.magic.invoke", parameters, "heal").status_code
            == 500
        )
    finally:
        repository.evidence_persister = original
    body = next(
        row
        for row in player.get(path + "/scene").get_json()["perceived_entities"]
        if row["entity_id"] == card["entity_id"]
    )
    assert body["mana"] == 8 and body["health"] == 5
    response = command(player, base, card, "tabletop.magic.invoke", parameters, "heal")
    assert response.status_code == 200, response.get_json()
    assert (
        command(player, base, card, "tabletop.magic.invoke", parameters, "heal").get_json()
        == response.get_json()
    )
    body = next(
        row
        for row in player.get(path + "/scene").get_json()["perceived_entities"]
        if row["entity_id"] == card["entity_id"]
    )
    assert body["mana"] == 6 and body["health"] == 9
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT payload->>'chosen_key' FROM cognition.human_choice_evidence WHERE run_id=%s",
            (run,),
        )
        assert cursor.fetchall() == [(f"spell:MEND:{card['entity_id']}",)]


def test_009_upgrade_and_repeat_with_preserved_old_evidence(
    integration_stack, monkeypatch, tmp_path
):
    name = "ttdm_tactics_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:9]:
            shutil.copy2(path, prior / path.name)
        assert migrate(url, prior) == 9
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
        app = create_app(artifact_root=tmp_path / "legacy")
        admin, player, card, path, run, target, base = setup_scene(app)
        provoke(admin, base, target, card, "legacy-threat")
        repository = app.extensions["simulation"].durable_repository
        original = repository.evidence_builder

        def legacy(proposal, before):
            bundle = original(proposal, before)
            if bundle and bundle.get("choices"):
                bundle["choices"]["version"] = "speech-combat-behavior-1.0.0"
                bundle["choices"]["options"] = [
                    row
                    for row in bundle["choices"]["options"]
                    if row["kind"] not in {"GUARD", "SPELL"}
                ]
            return bundle

        repository.evidence_builder = legacy
        try:
            response = command(
                player, base, card, "tabletop.spatial.move", {"dx": -1, "dy": 0}, "legacy-move"
            )
            assert response.status_code == 200, response.get_json()
        finally:
            repository.evidence_builder = original
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM cognition.human_choice_evidence")
            old_rows = cursor.fetchall()
            assert (
                len(old_rows) == 1 and old_rows[0][0]["version"] == "speech-combat-behavior-1.0.0"
            )
        assert migrate(url, migrations) == 1
        assert migrate(url, migrations) == 0
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM cognition.human_choice_evidence")
            assert cursor.fetchall() == old_rows
        response = command(player, base, card, "tabletop.combat.guard", {}, "new-guard")
        assert response.status_code == 200, response.get_json()
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload->>'version' FROM cognition.human_choice_evidence ORDER BY sequence"
            )
            assert cursor.fetchall() == [
                ("speech-combat-behavior-1.0.0",),
                ("speech-combat-behavior-1.1.0",),
            ]
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        maintenance.close()
