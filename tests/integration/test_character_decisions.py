from __future__ import annotations

import json
import os
import secrets
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.character_decisions import CharacterProposalReceipt
from cognition.postgres_decisions import PostgresCharacterProposals
from cognition.projector import ClaimedWorldEvent, WorldEventProjector
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.database import transaction
from tests.integration.test_clean_boot import (
    _free_port,
    _start_runtime,
    _stop_runtime,
    _wait_for_ready,
)
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.integration


def _cookie_proposal(base, path, run, cookie):
    request = Request(
        base + path + "/character-proposals",
        data=json.dumps({"run_id": run, "idempotency_key": "process"}).encode(),
        headers={
            "Content-Type": "application/json",
            "Cookie": "ttdm_session=" + cookie,
            "Origin": base,
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def setup(integration_stack, monkeypatch, tmp_path):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = token
    scope = admin.post(
        "/api/v2/worlds", json={"name": "Proposal isolation " + uuid.uuid4().hex}
    ).get_json()
    return app, setup_bound_character(app, token, scope=scope)


def test_character_advice_restart_fresh_state_rls_and_kernel_commit(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    body = {"run_id": run, "idempotency_key": "durable-character-advice"}
    result = player.post(path + "/character-proposals", json=body)
    assert result.status_code == 200, result.get_json()
    receipt = result.get_json()
    assert receipt["committed"] is False
    # A separate application advances the world; the original API cache is stale.
    restarted = create_app(artifact_root=tmp_path)
    other = restarted.test_client()
    other.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert other.post(path + "/character-proposals", json=body).get_json() == receipt
    applied = other.post("/api/v2/commands", json=receipt["outcome"]["proposal"])
    assert applied.status_code == 200, applied.get_json()
    assert player.post(path + "/character-proposals", json=body).get_json() == receipt
    fresh = player.post(
        path + "/character-proposals", json={**body, "idempotency_key": "fresh-after-other-process"}
    )
    assert fresh.status_code == 200, fresh.get_json()
    assert fresh.get_json()["projection_version"] > receipt["projection_version"]
    assert fresh.get_json()["context_hash"] != receipt["context_hash"]
    assert card["entity_id"] not in json.dumps(receipt.get("situation", {}))
    actor = uuid.UUID(receipt["actor_id"])
    _, stranger, _, _, _, _, _ = setup_bound_character(
        app,
        scope={
            "world_id": receipt["scope"]["world_id"],
            "canonical_branch_id": receipt["scope"]["branch_id"],
            "current_run_id": run,
        },
    )
    stranger_actor = uuid.UUID(stranger.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    for observer, expected in [(actor, 2), (stranger_actor, 0), (uuid.uuid4(), 0), (None, 0)]:
        with transaction(actor_id=observer, dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM cognition.character_proposal_receipts WHERE entity_id=%s",
                    (card["entity_id"],),
                )
                assert cursor.fetchone()[0] == expected
    for operation in [
        "UPDATE cognition.character_proposal_receipts SET seed=0",
        "DELETE FROM cognition.character_proposal_receipts",
    ]:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(operation)
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            with psycopg2.connect(integration_stack.admin_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(operation)


def test_character_advice_concurrent_retry_and_atomic_trace_rollback(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    first = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "template"}
    )
    assert first.status_code == 200, first.get_json()
    receipt = CharacterProposalReceipt.model_validate(first.get_json())
    repository = PostgresCharacterProposals(integration_stack.database_url)
    calls = []
    candidate = receipt.model_copy(
        update={
            "idempotency_key": "concurrent",
            "decision_id": uuid.uuid4(),
        }
    )
    # Build a valid independent trace identity while preserving its pinned inputs.
    trace = receipt.outcome.trace.model_copy(update={"trace_id": candidate.decision_id})
    proposal = receipt.outcome.proposal.model_copy(
        update={
            "command_id": uuid.uuid4(),
            "decision_trace_id": candidate.decision_id,
        }
    )
    candidate = candidate.model_copy(
        update={
            "outcome": receipt.outcome.model_copy(update={"trace": trace, "proposal": proposal}),
        }
    )

    def factory():
        calls.append(True)
        return candidate

    def submit(_):
        return repository.get_or_create(receipt.scope, receipt.actor_id, "concurrent", factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert len(calls) == 1 and results[0] == results[1]
    # A late receipt FK error rolls back the previously inserted decision trace.
    broken_id = uuid.uuid4()
    broken = candidate.model_copy(
        update={
            "decision_id": broken_id,
            "binding_id": uuid.uuid4(),
            "idempotency_key": "rollback",
            "outcome": candidate.outcome.model_copy(
                update={
                    "trace": trace.model_copy(update={"trace_id": broken_id}),
                    "proposal": proposal.model_copy(update={"decision_trace_id": broken_id}),
                }
            ),
        }
    )
    with pytest.raises(ValueError, match="could not be stored"):
        repository.get_or_create(receipt.scope, receipt.actor_id, "rollback", lambda: broken)
    with transaction(actor_id=receipt.actor_id, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM cognition.decision_traces WHERE id=%s", (str(broken_id),)
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM cognition.character_proposal_receipts WHERE decision_id=%s",
                (str(broken_id),),
            )
            assert cursor.fetchone()[0] == 0


def test_upgrade_from_005_and_idempotent_rerun(integration_stack, tmp_path):
    name = "ttdm_proposal_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:5]:
            shutil.copy2(path, prior / path.name)
        assert migrate(url, prior) == 5
        assert migrate(url, migrations) == 1
        assert migrate(url, migrations) == 0
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid='cognition.character_proposal_receipts'::regclass"
            )
            assert cursor.fetchone() == (True, True)
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (name,)
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        maintenance.close()


def test_receipt_constraints_grants_and_fail_closed_insert(
    integration_stack, monkeypatch, tmp_path
):
    _, (_, player, _, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    response = player.post(
        path + "/character-proposals",
        json={"run_id": run, "idempotency_key": "constraint-template"},
    )
    assert response.status_code == 200
    receipt = response.get_json()
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(r) FROM cognition.character_proposal_receipts r "
            "WHERE decision_id=%s",
            (receipt["decision_id"],),
        )
        row = cursor.fetchone()[0]
    insert = (
        "INSERT INTO cognition.character_proposal_receipts "
        "SELECT * FROM jsonb_populate_record("
        "NULL::cognition.character_proposal_receipts, %s::jsonb)"
    )
    invalid = [
        ("idempotency_key", ""),
        ("idempotency_key", "x" * 201),
        ("context_hash", "invalid"),
        ("projection_version", -1),
        ("seed", -1),
    ]
    for key, value in invalid:
        with pytest.raises(psycopg2.errors.CheckViolation):
            with psycopg2.connect(integration_stack.admin_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(insert, (json.dumps({**row, key: value}),))
    for key in [
        "decision_id",
        "actor_id",
        "idempotency_key",
        "binding_id",
        "character_id",
        "context_hash",
        "projection_version",
        "seed",
        "authorship",
        "execution_mode",
        "committed",
        "scope",
    ]:
        payload = {**row["payload"], key: "forged"}
        with pytest.raises(psycopg2.errors.CheckViolation):
            with psycopg2.connect(integration_stack.admin_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(insert, (json.dumps({**row, "payload": payload}),))
    # Distinct private binding and trace foreign keys both reject missing lineage.
    for column in ["decision_id", "binding_id"]:
        missing = str(uuid.uuid4())
        new_trace = str(uuid.uuid4())
        data = {**row, "decision_id": new_trace, column: missing, "idempotency_key": "fk-" + column}
        data["payload"] = {
            **row["payload"],
            "decision_id": data["decision_id"],
            column: missing,
            "idempotency_key": data["idempotency_key"],
        }
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            with psycopg2.connect(integration_stack.admin_url) as connection:
                with connection.cursor() as cursor:
                    if column == "binding_id":
                        cursor.execute(
                            "INSERT INTO cognition.decision_traces SELECT * FROM "
                            "jsonb_populate_record(NULL::cognition.decision_traces, "
                            "(SELECT to_jsonb(t) || jsonb_build_object('id', %s) "
                            "FROM cognition.decision_traces t WHERE id=%s))",
                            (new_trace, receipt["decision_id"]),
                        )
                    cursor.execute(insert, (json.dumps(data),))
    for actor in [None, uuid.uuid4()]:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(insert, (json.dumps(row),))


def test_advice_receipt_survives_real_runtime_restart(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    # Use a real player cookie in each fresh process; never rewrite body control.
    environment = os.environ.copy()
    environment.update(
        {
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path),
            "TTDM_LLM_MODE": "mock",
        }
    )
    environment.pop("QDRANT_URL", None)
    original = None
    for _ in range(2):
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        process = _start_runtime(port, environment)
        try:
            assert _wait_for_ready(process, base)["storage_mode"] == "postgres"
            receipt = _cookie_proposal(base, path, run, player.get_cookie("ttdm_session").value)
            if original is None:
                original = receipt
            assert receipt == original
        finally:
            _stop_runtime(process)


def test_advice_waits_for_external_projector_without_clobbering_cache(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, player, card, _, path, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    simulation = app.extensions["simulation"]
    captured = []
    simulation.configure_subjective_projector(captured.append)
    branch = path.split("/branches/")[1].split("/")[0]
    spoken = player.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": card["world_id"],
            "branch_id": branch,
            "run_id": run,
            "embodied_entity_id": card["entity_id"],
            "parameters": {"text": "The gardener promised to stay here."},
            "idempotency_key": "delayed-private-knowledge",
        },
    )
    assert spoken.status_code == 200
    request = {"run_id": run, "idempotency_key": "after-external-projector"}
    pending = player.post(path + "/character-proposals", json=request)
    assert pending.status_code == 409 and pending.get_json()["error"] == "character_context_pending"
    actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM cognition.character_proposal_receipts WHERE entity_id=%s",
                (card["entity_id"],),
            )
            assert cursor.fetchone()[0] == 0
    receipt = captured[0]
    projector = WorldEventProjector(integration_stack.database_url)
    item = ClaimedWorldEvent(0, receipt.event, receipt.perceptions)
    # Exercise delivery acknowledgement too; do not leave another pending outbox
    # entry behind in the integration suite's shared database.
    assert projector.run_once(limit=1000) >= 1
    projector._project(item)
    assert player.post(path + "/character-proposals", json=request).status_code == 200
    assert (
        app.extensions["minds"].inspect(uuid.UUID(card["entity_id"]), branch_id=uuid.UUID(branch))[
            "observations"
        ]
        == []
    )
