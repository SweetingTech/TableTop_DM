from __future__ import annotations

import os
import secrets
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from domains.tabletop.character_bindings import (
    CharacterBinding,
    PostgresCharacterBindings,
    new_binding,
)
from domains.tabletop.portal import PostgresPortalRepository
from infra.migrate import migrate
from kernel.api.app import create_app
from kernel.database import transaction
from tests.integration.test_clean_boot import (
    _api_json,
    _free_port,
    _start_runtime,
    _stop_runtime,
    _wait_for_ready,
)
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.integration


def test_durable_card_binding_restart_rls_and_immutability(
    integration_stack, monkeypatch, tmp_path
):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app, token)
    history_path = f"/api/v2/player/characters/{card['character_id']}/history"
    history = player.get(history_path).get_json()["items"]
    assert len(history) == 1 and history[0]["card_version"] == card["card_version"]
    initial = player.get(path + "/context").get_json()
    assert initial["binding"]["card_revision_id"] == history[0]["revision_id"]
    assert initial["situation"]["identity"]["backstory"] == "Raised by sailors."
    assert (
        player.patch(
            f"/api/v2/player/characters/{card['character_id']}",
            json={"authored_identity": {"backstory": "A later card."}},
        ).status_code
        == 200
    )
    assert player.get(path + "/context").get_json() == initial
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert restored.get(path + "/context").get_json() == initial
    assert restored.get(history_path).get_json()["items"][0] == history[0]
    _, stranger, _, _, _, _, _ = setup_bound_character(app, token)
    assert stranger.get(history_path).status_code == 403
    assert stranger.get(path + "/context").status_code == 403
    stranger_actor = stranger.get("/api/v2/auth/session").get_json()["user"]["actor_id"]
    stranger_user = stranger.get("/api/v2/auth/session").get_json()["user"]["user_id"]
    other_world = admin.post("/api/v2/worlds", json={"name": "Other binding authority"}).get_json()[
        "world_id"
    ]
    assert (
        admin.put(
            f"/api/v2/admin/users/{stranger_user}/worlds/{other_world}/roles",
            json={"roles": ["DM"]},
        ).status_code
        == 200
    )
    for actor in [None, stranger_actor, str(uuid.uuid4())]:
        with transaction(
            actor_id=uuid.UUID(actor) if actor else None, dsn=integration_stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM tabletop.character_bindings WHERE character_id=%s",
                    (card["character_id"],),
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    "SELECT count(*) FROM tabletop.character_card_revisions WHERE character_id=%s",
                    (card["character_id"],),
                )
                assert cursor.fetchone()[0] == 0
    with pytest.raises(psycopg2.errors.RaiseException):
        with transaction(
            actor_id=uuid.UUID(stranger_actor), dsn=integration_stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tabletop.characters WHERE id=%s", (card["character_id"],)
                )
    with pytest.raises(psycopg2.errors.RaiseException):
        with transaction(
            actor_id=app.extensions["demo_ids"]["actor_id"], dsn=integration_stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tabletop.characters SET owner_user_id=%s WHERE id=%s",
                    (stranger_user, card["character_id"]),
                )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with transaction(
            actor_id=uuid.UUID(stranger_actor), dsn=integration_stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tabletop.characters SET name='Forged identity' WHERE id=%s",
                    (card["character_id"],),
                )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with transaction(
            actor_id=app.extensions["demo_ids"]["actor_id"], dsn=integration_stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE tabletop.character_bindings SET compiler_version='forged'")
    for table in ["tabletop.character_card_revisions", "tabletop.character_bindings"]:
        with pytest.raises(
            (psycopg2.errors.RaiseException, psycopg2.errors.ObjectNotInPrerequisiteState)
        ):
            with psycopg2.connect(integration_stack.admin_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f"UPDATE {table} SET recorded_at=now()")
    # An unbound card is an explicit consent deletion; bound history is retained.
    unbound = player.post(
        "/api/v2/player/characters",
        json={"world_id": card["world_id"], "name": "Delete private card"},
    ).get_json()
    assert player.delete(f"/api/v2/player/characters/{unbound['character_id']}").status_code == 204
    assert player.delete(f"/api/v2/player/characters/{card['character_id']}").status_code == 400


def test_binding_constraints_cas_race_and_atomic_mind_rollback(
    integration_stack, monkeypatch, tmp_path
):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app, token)
    base = CharacterBinding.model_validate(player.get(path + "/context").get_json()["binding"])
    actor = app.extensions["demo_ids"]["actor_id"]
    repository = PostgresCharacterBindings(integration_stack.database_url)
    history_path = f"/api/v2/player/characters/{card['character_id']}/history"
    choices = []
    for name in ["First revision", "Second revision"]:
        assert (
            player.patch(
                f"/api/v2/player/characters/{card['character_id']}", json={"name": name}
            ).status_code
            == 200
        )
        revision = player.get(history_path).get_json()["items"][-1]
        choices.append(
            new_binding(
                character_id=base.character_id,
                card_revision_id=uuid.UUID(revision["revision_id"]),
                scope=base.scope,
                persona_id=base.persona_id,
                persona_version_id=base.persona_version_id,
                compiler_version=base.compiler_version,
                actor_id=actor,
                replaces_binding_id=base.binding_id,
            )
        )

    def save(row):
        try:
            return repository.save(row, actor_id=actor)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, choices))
    assert sum(row is not None for row in results) == 1
    winner = next(row for row in results if row)
    assert repository.latest(base.scope, actor_id=actor) == winner
    assert repository.save(winner, actor_id=actor) == winner
    with pytest.raises(ValueError, match="retry differs"):
        repository.save(winner.model_copy(update={"compiler_version": "forged"}), actor_id=actor)

    def insert_invalid(changes):
        values = winner.model_copy(
            update={"binding_id": uuid.uuid4(), "replaces_binding_id": winner.binding_id, **changes}
        ).model_dump(mode="json")
        with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tabletop.character_bindings ("
                    + ",".join(values)
                    + ") VALUES ("
                    + ",".join(["%s"] * len(values))
                    + ")",
                    tuple(values.values()),
                )

    for changes in [
        {"card_revision_id": uuid.uuid4()},
        {"persona_version_id": uuid.uuid4()},
        {"run_id": uuid.uuid4(), "replaces_binding_id": None},
    ]:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            insert_invalid(changes)
    with pytest.raises(psycopg2.errors.CheckViolation):
        insert_invalid({"purpose": "SIMULATED_PLAYTESTER"})
    evaluation = admin.post("/api/v2/personas/generate", json={"seed": 98123}).get_json()
    evaluation_profile = admin.post(
        f"/api/v2/personas/{evaluation['persona_id']}/compile"
    ).get_json()
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        insert_invalid(
            {
                "persona_id": uuid.UUID(evaluation_profile["persona_id"]),
                "persona_version_id": uuid.UUID(evaluation_profile["persona_version"]),
            }
        )
    with pytest.raises(psycopg2.errors.RaiseException):
        insert_invalid({"entity_id": uuid.uuid4(), "replaces_binding_id": None})
    # The archive writer is a trigger, but its owner still cannot create malformed
    # content, invalid revision numbers, or duplicate revision identities.
    for number, content, error in [
        (0, "{}", psycopg2.errors.CheckViolation),
        (99, "[]", psycopg2.errors.CheckViolation),
        (1, "{}", psycopg2.errors.UniqueViolation),
    ]:
        with pytest.raises(error):
            with (
                psycopg2.connect(integration_stack.admin_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO tabletop.character_card_revisions"
                    "(character_id,revision_number,content) VALUES (%s,%s,%s::jsonb)",
                    (card["character_id"], number, content),
                )
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with psycopg2.connect(integration_stack.admin_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM cognition.mind_states WHERE "
                    "(world_id,branch_id,entity_id)=(%s,%s,%s)",
                    tuple(map(str, (base.world_id, base.branch_id, base.entity_id))),
                )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tabletop.character_card_revisions"
                    "(character_id,revision_number,content) VALUES (%s,99,'{}')",
                    (card["character_id"],),
                )
    # A failing first binding rolls back its provisional neutral mind.
    unbound = admin.post(
        "/api/v2/player/characters", json={"world_id": str(base.world_id), "name": "Rollback body"}
    ).get_json()
    body = uuid.uuid4()
    spawned = admin.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.entity.spawn",
            "world_id": str(base.world_id),
            "branch_id": str(base.branch_id),
            "run_id": run,
            "idempotency_key": "rollback-body-" + str(body),
            "parameters": {
                "entity_id": str(body),
                "name": "Rollback body",
                "entity_type": "NPC",
                "public_state": {"x": 20, "y": 20},
                "controller_actor_id": str(actor),
            },
        },
    )
    assert spawned.status_code == 200
    with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tabletop.characters SET entity_id=%s WHERE id=%s",
                (str(body), unbound["character_id"]),
            )
    revision = admin.get(f"/api/v2/player/characters/{unbound['character_id']}/history").get_json()[
        "items"
    ][0]
    invalid = new_binding(
        character_id=uuid.UUID(unbound["character_id"]),
        card_revision_id=uuid.UUID(revision["revision_id"]),
        scope=(base.world_id, base.branch_id, base.run_id, body),
        persona_id=base.persona_id,
        persona_version_id=uuid.uuid4(),
        compiler_version=base.compiler_version,
        actor_id=actor,
        replaces_binding_id=None,
    )
    with pytest.raises(ValueError):
        repository.save(invalid, actor_id=actor)
    with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM cognition.mind_states WHERE entity_id=%s", (str(body),)
            )
            assert cursor.fetchone()[0] == 0


def test_upgrade_from_004_backfills_legacy_card_once(integration_stack, tmp_path):
    name = "ttdm_card_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:4]:
            shutil.copy2(path, prior / path.name)
        migrate(url, prior)
        actor, user, card = (uuid.uuid4() for _ in range(3))
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sim.actors(id,actor_kind,display_name) VALUES (%s,'HUMAN','Legacy')",
                (str(actor),),
            )
            cursor.execute(
                "INSERT INTO identity.users(id,actor_id,username,password_hash) "
                "VALUES (%s,%s,'legacycard',%s)",
                (str(user), str(actor), "x" * 40),
            )
            cursor.execute(
                "INSERT INTO tabletop.characters(id,owner_user_id,name,species,class_name) "
                "VALUES (%s,%s,'Élan','Elf','Ranger')",
                (str(card), str(user)),
            )
        before = PostgresPortalRepository(url).get_character(card)
        assert before is not None
        migrate(url, migrations)
        rows = PostgresPortalRepository(url).character_revisions(card, actor_id=actor)
        assert len(rows) == 1 and rows[0].card_version == before.card_version
        assert rows[0].content.authored_identity.backstory == ""
        migrate(url, migrations)
        assert PostgresPortalRepository(url).character_revisions(card, actor_id=actor) == rows
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.actor_id=%s", (str(actor),))
            cursor.execute(
                "UPDATE tabletop.characters SET current_hit_points=0 WHERE id=%s", (str(card),)
            )
        assert len(PostgresPortalRepository(url).character_revisions(card, actor_id=actor)) == 1
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (name,)
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        maintenance.close()


def test_bound_identity_survives_two_real_api_processes(integration_stack, monkeypatch, tmp_path):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app, token)
    initial = admin.get(path + "/context", query_string={"run_id": run}).get_json()
    assert (
        player.patch(
            f"/api/v2/player/characters/{card['character_id']}",
            json={"name": "Edited while pinned"},
        ).status_code
        == 200
    )
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_OPERATOR_TOKEN": token,
            "TTDM_ARTIFACT_ROOT": str(tmp_path),
            "TTDM_LLM_MODE": "mock",
        }
    )
    environment.pop("QDRANT_URL", None)
    for _ in range(2):
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        process = _start_runtime(port, environment)
        try:
            assert _wait_for_ready(process, base)["storage_mode"] == "postgres"
            assert _api_json(base, path + "/context?run_id=" + run, token=token) == initial
            history = _api_json(
                base, f"/api/v2/player/characters/{card['character_id']}/history", token=token
            )
            assert isinstance(history, dict) and len(history["items"]) == 2
        finally:
            _stop_runtime(process)
