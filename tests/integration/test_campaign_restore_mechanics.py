from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from domains.tabletop.action_time import ACTION_TIME, wait_seconds
from domains.tabletop.economy import OFFERS
from domains.tabletop.initiative import ENCOUNTERS
from domains.tabletop.recovery import VITALS
from infra.migrate import discover, migrate
from kernel import campaign_revisions, revision_activation
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_death_recovery_api import defeat
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_trade_offers_api import prepare_trade
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration


def test_rewind_restores_live_mechanics_and_can_continue_the_encounter(
    isolated_integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(isolated_integration_stack, monkeypatch, tmp_path)
    admin, player, card, _path, run, target, base = game
    _, merchant, _, _ = prepare_trade(app, game)
    defeat(app, game)
    api_command(
        admin,
        base,
        "tabletop.encounter.start",
        {"participants": [card["entity_id"], merchant]},
        "checkpoint-encounter",
    )
    api_command(
        admin,
        base,
        "tabletop.condition.apply",
        {"target_id": merchant, "condition": "poisoned", "duration_seconds": 24},
        "checkpoint-condition",
    )
    load = app.extensions["world_runner"].snapshot
    previous = load().states.get(uuid.UUID(base["branch_id"]))
    archived = previous.projections
    checkpoint = manual_capture(admin, base)
    advance_clock(admin, base, 40)
    assert (
        not load()
        .states.get(previous.branch_id)
        .projections["tabletop.entities"][merchant]["timed_conditions"]
    )
    plan = request_for(checkpoint)
    root = revision_path(base)
    prepared = admin.post(root, json=plan)
    assert prepared.status_code == 200, prepared.get_json()
    prepared = prepared.get_json()
    assert prepared["provenance"]["restore_version"] == "campaign-restore-1.2.0"
    activation = f"{root}/{plan['request_id']}/activate"

    # Exercise the SQL guard below the Python validation, then retry the original plan.
    with monkeypatch.context() as patch:
        patch.setattr(revision_activation, "stable_hash", lambda value: "0" * 64)
        invalid = admin.post(activation)
    assert invalid.status_code == 409, invalid.get_json()
    assert invalid.get_json()["details"] == "campaign revision failed durable validation"
    assert (
        admin.get(f"/api/v2/worlds/{base['world_id']}").get_json()["canonical_branch_id"]
        == base["branch_id"]
    )

    fresh, operator = fresh_client(tmp_path)
    result = operator.post(activation)
    assert result.status_code == 200, result.get_json()
    receipt = result.get_json()["receipt"]
    assert receipt["state_hash"] == prepared["candidate_state_hash"]
    restored = (
        fresh.extensions["world_runner"].snapshot().states.get(uuid.UUID(receipt["branch_id"]))
    )
    new = {key: receipt[key] for key in ("world_id", "branch_id", "run_id")}
    for namespace in (ACTION_TIME, ENCOUNTERS, OFFERS, VITALS):
        assert archived[namespace]
        assert all(row["run_id"] == run for row in archived[namespace].values())
        assert restored.projections[namespace] == {
            key: {**row, "run_id": new["run_id"]} for key, row in archived[namespace].items()
        }
    original_conditions = archived["tabletop.entities"][merchant]["timed_conditions"]
    assert original_conditions
    assert restored.projections["tabletop.entities"][merchant]["timed_conditions"] == {
        key: {**row, "run_id": new["run_id"]} for key, row in original_conditions.items()
    }
    assert restored.projections[VITALS][target]["next_save_seconds"] == 6
    paused = command(
        player, new, card, "tabletop.dialogue.speak", {"text": "Ready."}, "while-paused"
    )
    assert paused.status_code == 409, paused.get_json()
    assert paused.get_json()["error"] == "restored_campaign_paused"
    resumed = operator.post(
        f"{root}/{plan['request_id']}/resume",
        json={"request_id": str(uuid.uuid4()), "expected_epoch": 1, "run_clock": False},
    )
    assert resumed.status_code == 200, resumed.get_json()
    ready = wait_seconds(restored, uuid.UUID(card["entity_id"]))
    assert ready >= 6
    advance_clock(operator, new, ready)

    def move():
        return command(
            player, new, card, "tabletop.spatial.move", {"dx": -1, "dy": 0}, "after-rewind"
        )

    moved = move()
    assert moved.status_code == 200, moved.get_json()
    retry = move()
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json()["event"]["event_id"] == moved.get_json()["event"]["event_id"]
    replay = operator.get(f"/api/v2/branches/{new['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_029_upgrade_keeps_a_compatible_prepared_plan_activatable(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_mechanics_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    runtime = make_dsn(stack.database_url, dbname=name)
    old = replace(stack, admin_url=owner, database_url=runtime)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:28]:
        shutil.copy2(migrations / item.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 28
            _, (admin, _, _, _, _, _, base) = prepare(old, monkeypatch, tmp_path)
            plan = request_for(manual_capture(admin, base))
            root = revision_path(base)
            provenance = campaign_revisions.revision_provenance

            def previous_provenance(*args):
                return provenance(*args).model_copy(
                    update={"restore_version": "campaign-restore-1.1.0"}
                )

            with monkeypatch.context() as patch:
                patch.setattr(campaign_revisions, "revision_provenance", previous_provenance)
                prepared = admin.post(root, json=plan)
            assert prepared.status_code == 200, prepared.get_json()
            latest = migrations / "029_campaign_restore_mechanics.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regprocedure('sim.require_restored_mechanics_hash()')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0
            _, operator = fresh_client(tmp_path)
            restored = operator.post(f"{root}/{plan['request_id']}/activate")
            assert restored.status_code == 200, restored.get_json()
            assert (
                restored.get_json()["receipt"]["state_hash"]
                == prepared.get_json()["candidate_state_hash"]
            )
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
