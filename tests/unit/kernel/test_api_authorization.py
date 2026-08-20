"""Session-bound authorization for the kernel API.

Every test here drives the browser boundary: the operator token is configured but never sent,
so `create_app` requires a real `ttdm_session` cookie instead of falling back to the
reference-mode loopback administrator. The operator/automation boundary keeps its wider reach
and is covered separately in `test_v2_api.py`.
"""

from __future__ import annotations

import uuid

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit

ADMIN_PASSWORD = "Administrator-Pw-1"
DM_PASSWORD = "Dungeon-Master-Pw-1"
PLAYER_PASSWORD = "Player-Account-Pw-1"
GUEST_PASSWORD = "Guest-Account-Pw-1"


def _sign_in(app, username: str, password: str):
    """Return a client authenticated as `username` with the password change completed."""
    client = app.test_client()
    assert (
        client.post(
            "/api/v2/auth/login", json={"username": username, "password": password}
        ).status_code
        == 200
    )
    return client


def _provision(admin, username: str, temporary: str, final: str, app):
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": username,
            "temporary_password": temporary,
            "profile": {"display_name": username.title()},
        },
    )
    assert created.status_code == 201, created.get_json()
    user_id = created.get_json()["user"]["user_id"]
    client = _sign_in(app, username, temporary)
    assert (
        client.post(
            "/api/v2/auth/change-password",
            json={"current_password": temporary, "new_password": final},
        ).status_code
        == 200
    )
    return user_id, client


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    """One app with an administrator, a DM, a Player, and a roleless account.

    The operator token stays configured for the whole module because the authentication
    boundary reads it per request: without it the app would fall back to the reference-mode
    loopback administrator and no request would exercise the session path.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("TTDM_OPERATOR_TOKEN", "authorization-suite-token")
        patch.delenv("DATABASE_URL", raising=False)
        yield from _table(tmp_path_factory)


def _table(tmp_path_factory):
    app = create_app(artifact_root=tmp_path_factory.mktemp("authorization"))
    admin = _sign_in(app, "admin", "admin123")
    assert (
        admin.post(
            "/api/v2/auth/change-password",
            json={"current_password": "admin123", "new_password": ADMIN_PASSWORD},
        ).status_code
        == 200
    )

    ids = admin.get("/api/v2/bootstrap").get_json()["ids"]
    world_id = ids["world_id"]

    dm_id, dm = _provision(admin, "tabledm", "Temporary-DM-Pw-1", DM_PASSWORD, app)
    player_id, player = _provision(
        admin, "tableplayer", "Temporary-Player-Pw-1", PLAYER_PASSWORD, app
    )
    _, guest = _provision(admin, "tableguest", "Temporary-Guest-Pw-1", GUEST_PASSWORD, app)

    for user_id, roles in ((dm_id, ["DM"]), (player_id, ["PLAYER"])):
        assert (
            admin.put(
                f"/api/v2/admin/users/{user_id}/worlds/{world_id}/roles", json={"roles": roles}
            ).status_code
            == 200
        )

    # Role grants only reach an existing session on its next sign-in, so re-authenticate.
    dm = _sign_in(app, "tabledm", DM_PASSWORD)
    player = _sign_in(app, "tableplayer", PLAYER_PASSWORD)

    private_world = admin.post("/api/v2/worlds", json={"name": "Sealed Vault"})
    assert private_world.status_code == 201
    yield {
        "app": app,
        "admin": admin,
        "dm": dm,
        "player": player,
        "guest": guest,
        "ids": ids,
        "world_id": world_id,
        "private_world_id": private_world.get_json()["world_id"],
    }


def test_session_cannot_submit_a_command_as_another_actor(table):
    """A named actor would make the kernel's capability check self-issued."""
    ids = table["ids"]
    denied = table["player"].post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.console.submit",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "actor_id": ids["actor_id"],
            "parameters": {"text": "I speak with the administrator's authority."},
            "idempotency_key": "impersonation-attempt",
        },
    )
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "permission_denied"


def test_command_is_attributed_to_the_signed_in_actor(table):
    """The ledger must record who actually acted, not who the request claimed."""
    ids = table["ids"]
    account = table["player"].get("/api/v2/auth/session").get_json()["user"]
    accepted = table["player"].post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.console.submit",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "parameters": {"text": "The tavern falls silent."},
            "idempotency_key": "attributed-submission",
        },
    )
    assert accepted.status_code == 200, accepted.get_json()
    assert accepted.get_json()["event"]["actor_id"] == account["actor_id"]
    assert account["actor_id"] != ids["actor_id"]


def test_roleless_account_cannot_mutate_a_world(table):
    """No world role is no authority, whatever entity the request names."""
    ids = table["ids"]
    denied = table["guest"].post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.spatial.move",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "embodied_entity_id": ids["hero_id"],
            "parameters": {"dx": 1, "dy": 0},
            "idempotency_key": "roleless-move",
        },
    )
    assert denied.status_code == 403


def test_player_cannot_act_through_an_entity_it_does_not_control(table):
    """A Player may speak, but never move a character the DM controls."""
    ids = table["ids"]
    denied = table["player"].post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.spatial.move",
            "world_id": ids["world_id"],
            "branch_id": ids["branch_id"],
            "run_id": ids["run_id"],
            "embodied_entity_id": ids["hero_id"],
            "parameters": {"dx": 1, "dy": 0},
            "idempotency_key": "uncontrolled-move",
        },
    )
    assert denied.status_code == 403


def test_only_administrators_may_mint_actors(table):
    """A mintable capability set is a mintable authority."""
    forged = {
        "display_name": "Escalated",
        "kind": "HUMAN",
        "roles": ["ADMIN"],
        "capabilities": ["action.commit", "entity.control", "canonical.promote"],
        "world_id": table["world_id"],
    }
    assert table["player"].post("/api/v2/actors", json=forged).status_code == 403
    assert table["dm"].post("/api/v2/actors", json=forged).status_code == 403
    assert table["guest"].get("/api/v2/actors").status_code == 403
    assert table["admin"].post("/api/v2/actors", json=forged).status_code == 201


def test_world_reads_are_scoped_to_granted_worlds(table):
    """Authority is never unioned across worlds."""
    private = table["private_world_id"]
    player = table["player"]
    for path in (
        f"/api/v2/worlds/{private}",
        f"/api/v2/worlds/{private}/entities",
        f"/api/v2/worlds/{private}/actors",
        f"/api/v2/worlds/{private}/runs",
        f"/api/v2/worlds/{private}/snapshots",
    ):
        assert player.get(path).status_code == 403, path

    listed = {world["world_id"] for world in player.get("/api/v2/worlds").get_json()}
    assert private not in listed
    assert table["world_id"] in listed

    administered = table["admin"].get("/api/v2/worlds").get_json()
    assert private in {world["world_id"] for world in administered}


def test_branch_replay_is_world_scoped(table):
    """Replay returns whole projections, so it needs the same scope as the world itself."""
    admin = table["admin"]
    private = table["private_world_id"]
    branch_id = admin.get(f"/api/v2/worlds/{private}").get_json()["canonical_branch_id"]
    assert table["player"].get(f"/api/v2/branches/{branch_id}/replay").status_code == 403
    assert admin.get(f"/api/v2/branches/{branch_id}/replay").status_code == 200

    visible = {branch["world_id"] for branch in table["player"].get("/api/v2/branches").get_json()}
    assert private not in visible


def test_event_reads_cannot_borrow_another_actors_visibility(table):
    """Visibility is resolved from the reading actor, so the reader may not choose one."""
    ids = table["ids"]
    account = table["player"].get("/api/v2/auth/session").get_json()["user"]
    borrowed = table["player"].get(f"/api/v2/events?actor_id={ids['actor_id']}").get_json()
    own = table["player"].get("/api/v2/events").get_json()
    assert borrowed == own
    assert all(event["actor_id"] != ids["actor_id"] for event in borrowed) or all(
        account["actor_id"] in event["visible_to"] or event["actor_id"] == account["actor_id"]
        for event in borrowed
    )


def test_trial_results_require_the_administrator_role(table):
    """Trial outputs are experiment data, not table data."""
    assert table["player"].get(f"/api/v2/trials/{uuid.uuid4()}").status_code == 403
    assert table["player"].post("/api/v2/trials/compare", json={}).status_code == 403
    assert table["guest"].get("/api/v2/trials/compare").status_code == 403


def test_world_role_grant_provisions_kernel_authority(table):
    """Product roles reach the kernel only through explicit world grants."""
    ids = table["ids"]
    authorities = table["admin"].get(f"/api/v2/worlds/{ids['world_id']}/actors").get_json()
    by_actor = {row["actor_id"]: row for row in authorities}

    player = table["player"].get("/api/v2/auth/session").get_json()["user"]
    dm = table["dm"].get("/api/v2/auth/session").get_json()["user"]

    assert "PLAYER" in by_actor[player["actor_id"]]["roles"]
    assert "entity.read.secret" not in by_actor[player["actor_id"]]["capabilities"]
    assert "run.branch" not in by_actor[player["actor_id"]]["capabilities"]

    assert "GM" in by_actor[dm["actor_id"]]["roles"]
    assert "entity.read.secret" in by_actor[dm["actor_id"]]["capabilities"]
