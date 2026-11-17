from __future__ import annotations

import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from domains.tabletop.world_time import read_clock
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.database import transaction
from kernel.due_work import ClockLeaseLost, PostgresDueWork
from tests.integration.test_world_time import clock_path, prepare
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.integration


def running_clock(integration_stack, monkeypatch, tmp_path):
    app, (admin, _, _, _, _, _, base) = prepare(integration_stack, monkeypatch, tmp_path)
    initial = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": initial["executor_actor_id"],
            "paused": False,
            "wall_time": NOW.isoformat(),
            "seconds_per_tick": 5,
        },
        "enable-due-work",
    )
    source = app.extensions["world_runner"].snapshot()
    return app, admin, base, source, read_clock(source.states.get(uuid.UUID(base["branch_id"])))


def row(stack, base):
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT epoch, step, lease_token, attempts FROM sim.world_due_work "
            "WHERE (world_id,branch_id)=(%s,%s)",
            (base["world_id"], base["branch_id"]),
        )
        return cursor.fetchone()


def test_clock_lease_crash_reclaim_atomic_retry_and_pause(integration_stack, monkeypatch, tmp_path):
    stack = integration_stack
    app, admin, base, source, clock = running_clock(stack, monkeypatch, tmp_path)
    queue = PostgresDueWork(stack.database_url)
    scope = uuid.UUID(base["world_id"]), uuid.UUID(base["branch_id"])
    boundary = NOW + timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=2) as racers:
        tokens = list(racers.map(lambda _: queue.claim(*scope, clock, boundary), range(2)))
    assert sum(token is not None for token in tokens) == 1
    old = next(token for token in tokens if token is not None)
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sim.world_due_work SET lease_until=clock_timestamp() - interval '1 second' "
            "WHERE lease_token=%s",
            (str(old),),
        )
    fresh_app = create_app(artifact_root=tmp_path)
    runner = fresh_app.extensions["world_runner"]
    fresh = runner.queue.claim(*scope, clock, boundary)
    assert fresh is not None and fresh != old

    def tick(token):
        return CommandProposal(
            **base,
            actor_id=clock.executor_actor_id,
            command_type="tabletop.clock.tick",
            idempotency_key="recover-clock-lease",
            parameters={
                "epoch": clock.epoch,
                "step": clock.step,
                "wall_time": boundary.isoformat(),
                "lease_token": str(token),
            },
        )

    with pytest.raises(ClockLeaseLost):
        source.submit(tick(old))
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("injected event publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_insert_perceptions", fail)
        with pytest.raises(RuntimeError, match="injected"):
            source.submit(tick(fresh))
    assert repository._insert_perceptions == original
    assert row(stack, base) == (2, 0, str(fresh), 0)
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 0
    receipt = runner.snapshot().submit(tick(fresh))
    assert source.submit(tick(old)).event.event_id == receipt.event.event_id
    assert row(stack, base) == (2, 1, None, 0)
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 5
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 2,
            "executor_actor_id": str(clock.executor_actor_id),
            "wall_time": NOW.isoformat(),
            "paused": True,
        },
        "cancel-next-work",
    )
    assert row(stack, base) is None
    paused = admin.get(clock_path(base)).get_json()["clock"]
    assert paused["paused"] and paused["seconds"] == 5
    runner.run_once(boundary + timedelta(seconds=10))
    assert admin.get(clock_path(base)).get_json()["clock"] == paused
    assert row(stack, base) is None


def test_retry_backoff_and_actor_scope(integration_stack, monkeypatch, tmp_path):
    stack = integration_stack
    _, _, base, _, clock = running_clock(stack, monkeypatch, tmp_path)
    queue = PostgresDueWork(stack.database_url)
    scope = uuid.UUID(base["world_id"]), uuid.UUID(base["branch_id"])
    boundary = NOW + timedelta(seconds=1)
    with transaction(dsn=stack.database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM sim.world_due_work")
        assert cursor.fetchone()[0] == 0
    foreign = clock.model_copy(update={"executor_actor_id": uuid.uuid4()})
    assert queue.claim(*scope, foreign, boundary) is None
    token = queue.claim(*scope, clock, boundary)
    assert token is not None
    proposal = CommandProposal(
        **base,
        actor_id=clock.executor_actor_id,
        command_type="tabletop.clock.tick",
        idempotency_key="retry-clock-lease",
    )
    queue.retry(proposal, uuid.uuid4())
    assert row(stack, base) == (2, 0, str(token), 0)
    queue.retry(proposal, token)
    assert row(stack, base) == (2, 0, None, 1)
    assert queue.claim(*scope, clock, boundary) is None


def test_upgrade_backfills_only_running_canonical_clocks(integration_stack, tmp_path):
    name = "ttdm_due_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for path in sorted(migrations.glob("*.sql"))[:13]:
        shutil.copy2(path, prior / path.name)
    with closing(psycopg2.connect(integration_stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(url, prior) == 13
            executor, active, trial, paused = (str(uuid.uuid4()) for _ in range(4))
            with transaction(dsn=url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sim.actors(id,actor_kind,display_name) VALUES(%s,'AGENT','Clock')",
                    (executor,),
                )
                for branch_id, kind, stops in (
                    (active, "CANONICAL", False),
                    (trial, "TRIAL", False),
                    (paused, "CANONICAL", True),
                ):
                    world_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO sim.worlds(id,slug,name) VALUES(%s,%s,'Clock upgrade')",
                        (world_id, world_id),
                    )
                    cursor.execute(
                        "INSERT INTO sim.branches(id,world_id,branch_kind,name) "
                        "VALUES(%s,%s,%s,'Clock')",
                        (branch_id, world_id, kind),
                    )
                    cursor.execute(
                        "INSERT INTO sim.runs(id,world_id,branch_id,run_kind,status) "
                        "VALUES(%s,%s,%s,'LIVE','RUNNING')",
                        (run_id, world_id, branch_id),
                    )
                    state = {
                        "tabletop.clock": {
                            "singleton": {
                                "run_id": run_id,
                                "executor_actor_id": executor,
                                "epoch": 4,
                                "step": 7,
                                "seconds": 25,
                                "paused": stops,
                                "next_due": NOW.isoformat(),
                            }
                        }
                    }
                    cursor.execute(
                        "INSERT INTO sim.branch_projections(branch_id,world_id,state,state_hash) "
                        "VALUES(%s,%s,%s,%s)",
                        (branch_id, world_id, json.dumps(state), "0" * 64),
                    )
            assert migrate(url, migrations) == 1
            assert migrate(url, migrations) == 0
            with transaction(dsn=url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT branch_id,epoch,step,due_at,available_at,lease_token "
                    "FROM sim.world_due_work"
                )
                assert cursor.fetchall() == [(active, 4, 7, NOW, NOW, None)]
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
