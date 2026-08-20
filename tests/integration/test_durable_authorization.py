"""Durable-mode parity for session-bound authorization.

`AGENTS.md` requires local/reference and durable/RLS authorization to reach matching outcomes.
`tests/unit/kernel/test_api_authorization.py` pins the reference path; this module asserts the
same outcomes with `DATABASE_URL` set, where world grants also flow through
`sim.actor_roles`/`sim.actor_capabilities` and the reading actor selects the row-level-security
identity.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from infra.migrate import migrate
from kernel.api.app import create_app

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).resolve().parents[2] / "infra" / "sql" / "migrations"

ADMIN_PASSWORD = "Durable-Administrator-2026!"
PLAYER_PASSWORD = "Durable-Player-2026!"
OUTSIDER_PASSWORD = "Durable-Outsider-2026!"


def _account(admin, app, username: str, temporary: str, final: str):
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": username,
            "temporary_password": temporary,
            "profile": {"display_name": username.title()},
        },
    )
    assert created.status_code == 201, created.get_json()
    client = app.test_client()
    assert (
        client.post(
            "/api/v2/auth/login", json={"username": username, "password": temporary}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v2/auth/change-password",
            json={"current_password": temporary, "new_password": final},
        ).status_code
        == 200
    )
    return created.get_json()["user"]["user_id"], client


@pytest.fixture(scope="module")
def durable_database():
    """A database of this module's own.

    `integration_stack` is session-scoped and shared, and these tests must replace the
    bootstrap administrator's password to get past the forced first-login change — which would
    strand every other module that signs in as `admin`.
    """
    if os.environ.get("TTDM_INTEGRATION") != "1":
        pytest.skip("set TTDM_INTEGRATION=1 and start PostgreSQL to run integration tests")

    maintenance_url = os.environ.get(
        "TTDM_TEST_DATABASE_ADMIN_URL",
        "postgresql://postgres:postgres_dev_only@127.0.0.1:5432/postgres",
    )
    suffix = f"{os.getpid()}_{secrets.token_hex(3)}"
    database = f"tabletop_dm_authz_{suffix}"
    runtime_user = f"ttdm_authz_{suffix}"
    runtime_password = secrets.token_urlsafe(24)

    def connect():
        connection = psycopg2.connect(maintenance_url)
        connection.autocommit = True
        return connection

    maintenance = connect()
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    finally:
        maintenance.close()

    base, _, _ = maintenance_url.rpartition("/")
    admin_url = f"{base}/{database}"
    scheme, _, rest = base.partition("://")
    host = rest.rpartition("@")[2]
    runtime_url = f"{scheme}://{runtime_user}:{runtime_password}@{host}/{database}"
    migrate(
        admin_url,
        directory=MIGRATIONS,
        runtime_user=runtime_user,
        runtime_password=runtime_password,
    )
    yield runtime_url

    maintenance = connect()
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database,),
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime_user)))
    finally:
        maintenance.close()


@pytest.fixture(scope="module")
def durable_table(durable_database, tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", durable_database)
        patch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
        yield from _durable_table(tmp_path_factory)


def _durable_table(tmp_path_factory):
    app = create_app(artifact_root=tmp_path_factory.mktemp("durable-authz"))

    admin = app.test_client()
    assert (
        admin.post(
            "/api/v2/auth/login", json={"username": "admin", "password": "admin123"}
        ).status_code
        == 200
    )
    assert (
        admin.post(
            "/api/v2/auth/change-password",
            json={"current_password": "admin123", "new_password": ADMIN_PASSWORD},
        ).status_code
        == 200
    )

    ids = admin.get("/api/v2/bootstrap").get_json()["ids"]
    world_id = ids["world_id"]

    player_id, _ = _account(admin, app, "durableplayer", "Temporary-Player-2026!", PLAYER_PASSWORD)
    assert (
        admin.put(
            f"/api/v2/admin/users/{player_id}/worlds/{world_id}/roles", json={"roles": ["PLAYER"]}
        ).status_code
        == 200
    )
    player = app.test_client()
    assert (
        player.post(
            "/api/v2/auth/login", json={"username": "durableplayer", "password": PLAYER_PASSWORD}
        ).status_code
        == 200
    )

    _, outsider = _account(
        admin, app, "durableoutsider", "Temporary-Outsider-2026!", OUTSIDER_PASSWORD
    )

    sealed = admin.post("/api/v2/worlds", json={"name": "Sealed Vault"})
    assert sealed.status_code == 201
    yield {
        "admin": admin,
        "player": player,
        "outsider": outsider,
        "ids": ids,
        "world_id": world_id,
        "sealed_world_id": sealed.get_json()["world_id"],
    }


def test_durable_command_is_attributed_to_the_signed_in_actor(durable_table) -> None:
    """The durable ledger must record the caller, not an actor named by the request."""
    ids = durable_table["ids"]
    player = durable_table["player"]
    account = player.get("/api/v2/auth/session").get_json()["user"]

    impersonation = player.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.console.submit",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "actor_id": ids["actor_id"],
            "parameters": {"text": "I speak with the administrator's authority."},
            "idempotency_key": "durable-impersonation",
        },
    )
    assert impersonation.status_code == 403

    accepted = player.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.console.submit",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "parameters": {"text": "The tavern falls silent."},
            "idempotency_key": "durable-attributed",
        },
    )
    assert accepted.status_code == 200, accepted.get_json()
    assert accepted.get_json()["event"]["actor_id"] == account["actor_id"]
    assert account["actor_id"] != ids["actor_id"]


def test_durable_world_reads_are_scoped_to_granted_worlds(durable_table) -> None:
    """The Secret Vault case: a role in one world must reveal nothing of another."""
    sealed = durable_table["sealed_world_id"]
    for client in (durable_table["player"], durable_table["outsider"]):
        for path in (
            f"/api/v2/worlds/{sealed}",
            f"/api/v2/worlds/{sealed}/entities",
            f"/api/v2/worlds/{sealed}/actors",
            f"/api/v2/worlds/{sealed}/runs",
        ):
            assert client.get(path).status_code == 403, path
        listed = {world["world_id"] for world in client.get("/api/v2/worlds").get_json()}
        assert sealed not in listed

    administered = durable_table["admin"].get("/api/v2/worlds").get_json()
    assert sealed in {world["world_id"] for world in administered}


def test_durable_role_grant_provisions_kernel_authority(durable_table) -> None:
    """A product role must reach `sim.actor_capabilities`, not just the identity tables."""
    admin = durable_table["admin"]
    world_id = durable_table["world_id"]
    account = durable_table["player"].get("/api/v2/auth/session").get_json()["user"]

    authorities = admin.get(f"/api/v2/worlds/{world_id}/actors").get_json()
    granted = next(row for row in authorities if row["actor_id"] == account["actor_id"])

    assert "PLAYER" in granted["roles"]
    assert "action.propose" in granted["capabilities"]
    assert "entity.read.secret" not in granted["capabilities"]
    assert "canonical.promote" not in granted["capabilities"]


def test_durable_event_reads_cannot_borrow_another_actors_visibility(durable_table) -> None:
    """In durable mode the reading actor also selects the row-level-security identity."""
    ids = durable_table["ids"]
    admin = durable_table["admin"]
    player = durable_table["player"]

    # An administrator-only event: the demo actor holds `world.read.all`, the Player does not.
    spawned = admin.post(
        f"/api/v2/worlds/{ids['world_id']}/entities",
        json={
            "name": "Hidden Cultist",
            "entity_type": "NPC",
            "public_state": {"x": 9, "y": 9, "hp": 5, "max_hp": 5},
            "secret_state": {"plot": "betrays the party"},
        },
    )
    assert spawned.status_code == 201

    visible_to_admin = admin.get("/api/v2/events").get_json()
    own = player.get("/api/v2/events").get_json()
    borrowed = player.get(f"/api/v2/events?actor_id={ids['actor_id']}").get_json()

    # The test is only meaningful while the two views actually differ.
    assert len(visible_to_admin) > len(own)
    assert borrowed == own
    assert all(event["actor_id"] != ids["actor_id"] for event in borrowed)


def test_durable_actor_minting_requires_administrator(durable_table) -> None:
    forged = {
        "display_name": "Escalated",
        "kind": "HUMAN",
        "roles": ["ADMIN"],
        "capabilities": ["action.commit", "canonical.promote"],
        "world_id": durable_table["world_id"],
    }
    assert durable_table["player"].post("/api/v2/actors", json=forged).status_code == 403
    assert durable_table["outsider"].get("/api/v2/actors").status_code == 403
    assert durable_table["admin"].post("/api/v2/actors", json=forged).status_code == 201
