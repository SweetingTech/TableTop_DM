from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_json(
    base_url: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-TTDM-Operator-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned {exc.code}: {detail}") from exc


def _start_runtime(port: int, environment: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "main.py",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_ready(process: subprocess.Popen[str], base_url: str) -> dict:
    deadline = time.monotonic() + 30
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"runtime exited with {process.returncode}:\n{output}")
        try:
            readiness = _get_json(f"{base_url}/readyz")
            if readiness.get("ready") is True:
                return readiness
            last_error = str(readiness)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    pytest.fail(f"runtime readiness timed out: {last_error}")


def _stop_runtime(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_clean_runtime_boots_with_non_owner_database(integration_stack, tmp_path: Path) -> None:
    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_RNG_SEED": "1337",
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    qdrant_url = environment.get("TTDM_TEST_QDRANT_URL")
    if qdrant_url:
        environment["QDRANT_URL"] = qdrant_url
    else:
        environment.pop("QDRANT_URL", None)

    process = _start_runtime(port, environment)
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_ready(process, base_url)
        assert _get_json(f"{base_url}/healthz")["live"] is True
        readiness = _get_json(f"{base_url}/readyz")
        assert readiness["storage_mode"] == "postgres"
        assert readiness["checks"]["postgres"] == {
            "migration": "002_identity_and_tabletop_workspaces.sql",
            "ok": True,
        }
        with urllib.request.urlopen(f"{base_url}/v2", timeout=3) as response:
            assert response.status == 200
            assert b'<div id="root"></div>' in response.read()
    finally:
        _stop_runtime(process)


def test_restart_hydrates_created_world_projection_and_event(
    integration_stack,
    tmp_path: Path,
) -> None:
    token = "integration-operator-token"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "restart-artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_RNG_SEED": "1337",
            "TTDM_OPERATOR_TOKEN": token,
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    qdrant_url = environment.get("TTDM_TEST_QDRANT_URL")
    if qdrant_url:
        environment["QDRANT_URL"] = qdrant_url
    else:
        environment.pop("QDRANT_URL", None)

    first_port = _free_port()
    first_url = f"http://127.0.0.1:{first_port}"
    first = _start_runtime(first_port, environment)
    try:
        _wait_for_ready(first, first_url)
        bootstrap = _api_json(first_url, "/api/v2/bootstrap", token=token)
        assert isinstance(bootstrap, dict)
        actor_id = bootstrap["ids"]["actor_id"]
        name = f"Restart World {os.getpid()}"
        world = _api_json(
            first_url,
            "/api/v2/worlds",
            token=token,
            method="POST",
            payload={"name": name},
        )
        assert isinstance(world, dict)
        entity = _api_json(
            first_url,
            f"/api/v2/worlds/{world['world_id']}/entities",
            token=token,
            method="POST",
            payload={
                "name": "Restart Witness",
                "entity_type": "TEST_PLAYER",
                "public_state": {"x": 0, "y": 0},
                "secret_state": {"true_name": "Restart Secret"},
                "controller_actor_id": actor_id,
            },
        )
        assert isinstance(entity, dict)
        assert "secret_state" not in entity
        receipt = _api_json(
            first_url,
            "/api/v2/commands",
            token=token,
            method="POST",
            payload={
                "command_type": "tabletop.onboarding.act",
                "world_id": world["world_id"],
                "branch_id": world["canonical_branch_id"],
                "run_id": world["current_run_id"],
                "actor_id": actor_id,
                "embodied_entity_id": entity["entity_id"],
                "parameters": {"action": "START"},
                "idempotency_key": f"restart-event-{os.getpid()}",
                "seed": 17,
            },
        )
        assert isinstance(receipt, dict)
        event_id = receipt["event"]["event_id"]
        world_id = world["world_id"]
    finally:
        _stop_runtime(first)

    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT secret_state, controller_actor_id
                FROM sim.entities
                WHERE world_id=%s AND branch_id=%s AND id=%s
                """,
                (world_id, world["canonical_branch_id"], entity["entity_id"]),
            )
            secret_state, controller_actor_id = cursor.fetchone()
            assert secret_state == {"true_name": "Restart Secret"}
            assert controller_actor_id == actor_id
            cursor.execute(
                """
                SELECT command.parameters, command.result, event.payload, outbox.payload
                FROM sim.events event
                JOIN sim.command_log command
                  ON command.run_id=event.run_id
                 AND command.actor_id=event.actor_id
                 AND command.idempotency_key=event.idempotency_key
                JOIN sim.outbox outbox ON outbox.event_id=event.event_id
                WHERE event.event_id=%s
                """,
                (entity["creation_event_id"],),
            )
            parameters, result, event_payload, outbox_payload = cursor.fetchone()
            assert parameters["secret_state"] == "[REDACTED]"
            for public_record in (parameters, result, event_payload, outbox_payload):
                assert "Restart Secret" not in str(public_record)

    second_port = _free_port()
    second_url = f"http://127.0.0.1:{second_port}"
    second = _start_runtime(second_port, environment)
    try:
        _wait_for_ready(second, second_url)
        worlds = _api_json(second_url, "/api/v2/worlds", token=token)
        assert isinstance(worlds, list)
        restored = next(item for item in worlds if item["world_id"] == world_id)
        assert restored["name"] == name

        detail = _api_json(
            second_url,
            f"/api/v2/worlds/{world_id}",
            token=token,
        )
        assert isinstance(detail, dict)
        assert detail["projection_version"] >= 1
        assert detail["projections"]["tabletop.onboarding"][entity["entity_id"]]["step_index"] == 1

        events = _api_json(
            second_url,
            f"/api/v2/events?actor_id={actor_id}",
            token=token,
        )
        assert isinstance(events, list)
        assert any(item["event_id"] == event_id for item in events)
        restored_entities = _api_json(
            second_url,
            f"/api/v2/worlds/{world_id}/entities",
            token=token,
        )
        assert isinstance(restored_entities, list)
        restored_entity = next(
            item for item in restored_entities if item["entity_id"] == entity["entity_id"]
        )
        assert "secret_state" not in restored_entity
        scoped_actors = _api_json(
            second_url,
            f"/api/v2/worlds/{world_id}/actors",
            token=token,
        )
        assert isinstance(scoped_actors, list)
        controller = next(item for item in scoped_actors if item["actor_id"] == actor_id)
        assert entity["entity_id"] in controller["controlled_entity_ids"]
    finally:
        _stop_runtime(second)


def test_restart_rebuilds_replay_history_and_same_state_snapshot_boundaries(
    integration_stack,
    tmp_path: Path,
) -> None:
    token = "integration-replay-token"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "replay-restart-artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_OPERATOR_TOKEN": token,
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    environment.pop("QDRANT_URL", None)

    first_port = _free_port()
    first_url = f"http://127.0.0.1:{first_port}"
    first = _start_runtime(first_port, environment)
    try:
        _wait_for_ready(first, first_url)
        bootstrap = _api_json(first_url, "/api/v2/bootstrap", token=token)
        assert isinstance(bootstrap, dict)
        actor_id = bootstrap["ids"]["actor_id"]
        world = _api_json(
            first_url,
            "/api/v2/worlds",
            token=token,
            method="POST",
            payload={"name": f"Replay World {os.getpid()}"},
        )
        assert isinstance(world, dict)
        world_id = world["world_id"]
        branch_id = world["canonical_branch_id"]
        run_id = world["current_run_id"]
        zero = _api_json(
            first_url,
            f"/api/v2/worlds/{world_id}/snapshots",
            token=token,
            method="POST",
            payload={},
        )
        assert isinstance(zero, dict)
        first_receipt = _api_json(
            first_url,
            "/api/v2/commands",
            token=token,
            method="POST",
            payload={
                "command_type": "tabletop.console.submit",
                "world_id": world_id,
                "branch_id": branch_id,
                "run_id": run_id,
                "actor_id": actor_id,
                "parameters": {"text": "The first durable boundary."},
                "idempotency_key": f"replay-first-{os.getpid()}",
            },
        )
        assert isinstance(first_receipt, dict)
        one = _api_json(
            first_url,
            f"/api/v2/worlds/{world_id}/snapshots",
            token=token,
            method="POST",
            payload={},
        )
        assert isinstance(one, dict)
        assert zero["state_hash"] == one["state_hash"] == first_receipt["state_hash"]
        assert (zero["through_event_seq"], one["through_event_seq"]) == (0, 1)
        assert zero["snapshot_id"] != one["snapshot_id"]
    finally:
        _stop_runtime(first)

    second_port = _free_port()
    second_url = f"http://127.0.0.1:{second_port}"
    second = _start_runtime(second_port, environment)
    try:
        _wait_for_ready(second, second_url)
        replayed = _api_json(
            second_url,
            f"/api/v2/branches/{branch_id}/replay",
            token=token,
        )
        assert isinstance(replayed, dict)
        assert replayed["verified"] is True
        assert replayed["state_hash"] == one["state_hash"]
        assert replayed["projection_version"] == 1

        second_receipt = _api_json(
            second_url,
            "/api/v2/commands",
            token=token,
            method="POST",
            payload={
                "command_type": "tabletop.console.submit",
                "world_id": world_id,
                "branch_id": branch_id,
                "run_id": run_id,
                "actor_id": actor_id,
                "parameters": {"text": "The second durable boundary."},
                "idempotency_key": f"replay-second-{os.getpid()}",
            },
        )
        assert isinstance(second_receipt, dict)
        after = _api_json(
            second_url,
            f"/api/v2/branches/{branch_id}/replay",
            token=token,
        )
        assert isinstance(after, dict)
        assert after["verified"] is True
        assert after["projection_version"] == 2
        two = _api_json(
            second_url,
            f"/api/v2/worlds/{world_id}/snapshots",
            token=token,
            method="POST",
            payload={},
        )
        assert isinstance(two, dict)
        assert two["through_event_seq"] == 2
        assert two["state_hash"] == zero["state_hash"]
    finally:
        _stop_runtime(second)

    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT through_event_seq, state_hash
                FROM sim.snapshots
                WHERE world_id=%s AND source_branch_id=%s
                ORDER BY through_event_seq
                """,
                (world_id, branch_id),
            )
            assert cursor.fetchall() == [
                (0, zero["state_hash"]),
                (1, zero["state_hash"]),
                (2, zero["state_hash"]),
            ]


def test_population_target_and_full_lifecycle_survive_restarts(
    integration_stack,
    tmp_path: Path,
) -> None:
    token = "integration-population-token"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "population-restart-artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_OPERATOR_TOKEN": token,
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    environment.pop("QDRANT_URL", None)

    first_port = _free_port()
    first_url = f"http://127.0.0.1:{first_port}"
    first = _start_runtime(first_port, environment)
    try:
        _wait_for_ready(first, first_url)
        world = _api_json(
            first_url,
            "/api/v2/worlds",
            token=token,
            method="POST",
            payload={"name": f"Population Target {os.getpid()}"},
        )
        assert isinstance(world, dict)
        population = _api_json(
            first_url,
            "/api/v2/populations",
            token=token,
            method="POST",
            payload={
                "name": f"Restart population {os.getpid()}",
                "size": 4,
                "seed": 884,
                "world_id": world["world_id"],
                "branch_id": world["canonical_branch_id"],
            },
        )
        assert isinstance(population, dict)
        assert population["world_id"] == world["world_id"]
        assert population["branch_id"] == world["canonical_branch_id"]
        population_id = population["population_id"]
        sample = _api_json(
            first_url,
            f"/api/v2/populations/{population_id}/sample",
            token=token,
            method="POST",
            payload={"strata": [], "per_cell": 1, "seed": 1},
        )
        assert isinstance(sample, dict)
        selected = sample["items"][0]
        persona_id = selected["persona_id"]
        materialized = _api_json(
            first_url,
            f"/api/v2/populations/{population_id}/materialize",
            token=token,
            method="POST",
            payload={
                "persona_id": persona_id,
                "profile": selected["dimensions"],
                "persistent_state": {
                    "finances": {"coins": 10},
                    "history": ["arrived"],
                },
                "world_step": 4,
                "world_id": world["world_id"],
                "branch_id": world["canonical_branch_id"],
            },
        )
        assert isinstance(materialized, dict)
        assert materialized["version"] == 1
        activated = _api_json(
            first_url,
            f"/api/v2/populations/{population_id}/members/{persona_id}/activate",
            token=token,
            method="POST",
            payload={
                "active_state": {
                    "beliefs": ["market is unsafe"],
                    "finances": {"coins": 8},
                    "attention_budget": 75,
                },
                "world_step": 5,
                "world_id": world["world_id"],
                "branch_id": world["canonical_branch_id"],
            },
        )
        assert isinstance(activated, dict)
        compressed = _api_json(
            first_url,
            f"/api/v2/populations/{population_id}/members/{persona_id}/deactivate",
            token=token,
            method="POST",
            payload={
                "compressed_state": {"routine": "market"},
                "world_step": 9,
                "world_id": world["world_id"],
                "branch_id": world["canonical_branch_id"],
            },
        )
        assert isinstance(compressed, dict)
        assert compressed["version"] == 3
        assert compressed["compressed_state"] == {"routine": "market"}
    finally:
        _stop_runtime(first)

    second_port = _free_port()
    second_url = f"http://127.0.0.1:{second_port}"
    second = _start_runtime(second_port, environment)
    try:
        _wait_for_ready(second, second_url)
        pools = _api_json(second_url, "/api/v2/populations", token=token)
        assert isinstance(pools, list)
        restored_pool = next(item for item in pools if item["population_id"] == population_id)
        assert restored_pool["world_id"] == world["world_id"]
        assert restored_pool["branch_id"] == world["canonical_branch_id"]
        restored = _api_json(
            second_url,
            f"/api/v2/populations/{population_id}/members/{persona_id}",
            token=token,
        )
        assert isinstance(restored, dict)
        assert restored["version"] == 3
        assert restored["world_step"] == 9
        assert restored["active_state"] == {}
        assert restored["compressed_state"] == {"routine": "market"}
        assert restored["persistent_state"] == {
            "beliefs": ["market is unsafe"],
            "finances": {"coins": 8},
            "history": ["arrived"],
            "routine": "market",
        }
        transitions = _api_json(
            second_url,
            f"/api/v2/populations/{population_id}/transitions",
            token=token,
        )
        assert isinstance(transitions, list)
        assert [item["lifecycle_version"] for item in transitions] == [1, 2, 3]
        assert [item["world_step"] for item in transitions] == [4, 5, 9]

        reactivated = _api_json(
            second_url,
            f"/api/v2/populations/{population_id}/members/{persona_id}/activate",
            token=token,
            method="POST",
            payload={"active_state": {"attention_budget": 80}, "world_step": 10},
        )
        assert isinstance(reactivated, dict)
        assert reactivated["version"] == 4
    finally:
        _stop_runtime(second)

    third_port = _free_port()
    third_url = f"http://127.0.0.1:{third_port}"
    third = _start_runtime(third_port, environment)
    try:
        _wait_for_ready(third, third_url)
        active = _api_json(
            third_url,
            f"/api/v2/populations/{population_id}/members/{persona_id}",
            token=token,
        )
        assert isinstance(active, dict)
        assert active["level"] == "ACTIVE"
        assert active["version"] == 4
        assert active["world_step"] == 10
        assert active["active_state"] == {"attention_budget": 80}
    finally:
        _stop_runtime(third)


def test_world_scoped_actor_grants_do_not_union_after_restart(
    integration_stack,
    tmp_path: Path,
) -> None:
    token = "integration-authority-token"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "authority-restart-artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_OPERATOR_TOKEN": token,
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    environment.pop("QDRANT_URL", None)

    first_port = _free_port()
    first_url = f"http://127.0.0.1:{first_port}"
    first = _start_runtime(first_port, environment)
    try:
        _wait_for_ready(first, first_url)
        allowed_world = _api_json(
            first_url,
            "/api/v2/worlds",
            token=token,
            method="POST",
            payload={"name": f"Authority allowed {os.getpid()}"},
        )
        denied_world = _api_json(
            first_url,
            "/api/v2/worlds",
            token=token,
            method="POST",
            payload={"name": f"Authority denied {os.getpid()}"},
        )
        assert isinstance(allowed_world, dict)
        assert isinstance(denied_world, dict)
        scoped_actor = _api_json(
            first_url,
            "/api/v2/actors",
            token=token,
            method="POST",
            payload={
                "display_name": "One-world agent",
                "kind": "AGENT",
                "world_id": allowed_world["world_id"],
                "roles": ["TEST_PERSONA"],
                "capabilities": ["action.propose", "action.commit"],
            },
        )
        assert isinstance(scoped_actor, dict)
        actor_id = scoped_actor["actor_id"]
    finally:
        _stop_runtime(first)

    second_port = _free_port()
    second_url = f"http://127.0.0.1:{second_port}"
    second = _start_runtime(second_port, environment)
    try:
        _wait_for_ready(second, second_url)
        allowed_actors = _api_json(
            second_url,
            f"/api/v2/worlds/{allowed_world['world_id']}/actors",
            token=token,
        )
        denied_actors = _api_json(
            second_url,
            f"/api/v2/worlds/{denied_world['world_id']}/actors",
            token=token,
        )
        assert isinstance(allowed_actors, list)
        assert isinstance(denied_actors, list)
        assert actor_id in {item["actor_id"] for item in allowed_actors}
        assert actor_id not in {item["actor_id"] for item in denied_actors}

        accepted = _api_json(
            second_url,
            "/api/v2/commands",
            token=token,
            method="POST",
            payload={
                "command_type": "tabletop.console.submit",
                "world_id": allowed_world["world_id"],
                "branch_id": allowed_world["canonical_branch_id"],
                "run_id": allowed_world["current_run_id"],
                "actor_id": actor_id,
                "parameters": {"text": "Allowed only here."},
                "idempotency_key": f"authority-allowed-{os.getpid()}",
            },
        )
        assert isinstance(accepted, dict)

        denied_request = urllib.request.Request(
            f"{second_url}/api/v2/commands",
            data=json.dumps(
                {
                    "command_type": "tabletop.console.submit",
                    "world_id": denied_world["world_id"],
                    "branch_id": denied_world["canonical_branch_id"],
                    "run_id": denied_world["current_run_id"],
                    "actor_id": actor_id,
                    "parameters": {"text": "Must be denied."},
                    "idempotency_key": f"authority-denied-{os.getpid()}",
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-TTDM-Operator-Token": token,
            },
        )
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(denied_request, timeout=10)
        assert denied.value.code == 403
    finally:
        _stop_runtime(second)


def test_restart_restores_belief_revision_and_relationship_accumulation(
    integration_stack,
    tmp_path: Path,
) -> None:
    token = "integration-cognition-token"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": integration_stack.database_url,
            "REDIS_URL": integration_stack.redis_url,
            "TTDM_ARTIFACT_ROOT": str(tmp_path / "cognition-restart-artifacts"),
            "TTDM_LLM_MODE": "mock",
            "TTDM_OPERATOR_TOKEN": token,
        }
    )
    environment.pop("DATABASE_ADMIN_URL", None)
    qdrant_url = environment.get("TTDM_TEST_QDRANT_URL")
    if qdrant_url:
        environment["QDRANT_URL"] = qdrant_url
    else:
        environment.pop("QDRANT_URL", None)

    seed_port = _free_port()
    seed_url = f"http://127.0.0.1:{seed_port}"
    seed_process = _start_runtime(seed_port, environment)
    try:
        _wait_for_ready(seed_process, seed_url)
        bootstrap = _api_json(seed_url, "/api/v2/bootstrap", token=token)
        assert isinstance(bootstrap, dict)
        ids = bootstrap["ids"]
        entities = _api_json(
            seed_url,
            f"/api/v2/worlds/{ids['world_id']}/entities",
            token=token,
        )
        assert isinstance(entities, list)
        target_entity_id = next(
            item["entity_id"] for item in entities if item["entity_id"] != ids["hero_id"]
        )
        runtime_assignment = _api_json(
            seed_url,
            f"/api/v2/entities/{ids['hero_id']}/runtime",
            token=token,
            method="PUT",
            payload={
                "world_id": ids["world_id"],
                "branch_id": ids["branch_id"],
                "run_id": ids["run_id"],
                "runtime_kind": "UTILITY",
                "runtime_config": {"restart_fixture": True},
            },
        )
        assert isinstance(runtime_assignment, dict)
        assert runtime_assignment["runtime_kind"] == "UTILITY"
    finally:
        _stop_runtime(seed_process)

    first_event_id, second_event_id, correlation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    observed_at = datetime.now(UTC)
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            for event_id, status, created_at, causation_id in (
                (first_event_id, "OPEN", observed_at, None),
                (
                    second_event_id,
                    "CLOSED",
                    observed_at + timedelta(seconds=1),
                    first_event_id,
                ),
            ):
                cursor.execute(
                    """
                    INSERT INTO sim.events (
                      event_id, event_version, contract_version, world_id,
                      branch_id, run_id, actor_id, event_type, payload,
                      observed_by, visible_to, correlation_id, causation_id,
                      domain_tags, idempotency_key, created_at
                    ) VALUES (
                      %s, 2, '2.0.0', %s, %s, %s, %s, 'test.gate_status',
                      %s::jsonb, %s::uuid[], %s::uuid[], %s, %s,
                      ARRAY['test','cognition'], %s, %s
                    )
                    """,
                    (
                        str(event_id),
                        ids["world_id"],
                        ids["branch_id"],
                        ids["run_id"],
                        ids["actor_id"],
                        json.dumps(
                            {
                                "claims": [
                                    {
                                        "subject_type": "ENTITY",
                                        "subject_id": target_entity_id,
                                        "predicate": "gate_status",
                                        "value": status,
                                        "confidence": 1.0,
                                    }
                                ],
                                "summary": f"The gate is {status.casefold()}.",
                            }
                        ),
                        [ids["actor_id"]],
                        [ids["actor_id"]],
                        str(correlation_id),
                        str(causation_id) if causation_id else None,
                        f"cognition-restart-{event_id}",
                        created_at,
                    ),
                )

    first_port = _free_port()
    first_url = f"http://127.0.0.1:{first_port}"
    first = _start_runtime(first_port, environment)
    try:
        _wait_for_ready(first, first_url)
        restored_runtime = _api_json(
            first_url,
            f"/api/v2/entities/{ids['hero_id']}/runtime"
            f"?world_id={ids['world_id']}&branch_id={ids['branch_id']}&run_id={ids['run_id']}",
            token=token,
        )
        assert isinstance(restored_runtime, dict)
        assert restored_runtime["runtime_kind"] == "UTILITY"
        assert restored_runtime["runtime_config"] == {"restart_fixture": True}
        observed = _api_json(
            first_url,
            f"/api/v2/events/{first_event_id}/observe",
            token=token,
            method="POST",
            payload={
                "observer_actor_id": ids["actor_id"],
                "observer_entity_id": ids["hero_id"],
                "importance": 0.8,
            },
        )
        assert isinstance(observed, dict)
        assert observed["belief_revision"]["active_beliefs"][0]["value"] == "OPEN"
        relationship = _api_json(
            first_url,
            f"/api/v2/entities/{ids['hero_id']}/relationships",
            token=token,
            method="POST",
            payload={
                "target_entity_id": target_entity_id,
                "source_event_id": str(first_event_id),
                "event_type": "kept_promise",
            },
        )
        assert isinstance(relationship, dict)
        assert relationship["before"]["trust"] == 0
        assert relationship["after"]["trust"] == 12
        assert relationship["source_event_id"] == str(first_event_id)
    finally:
        _stop_runtime(first)

    second_port = _free_port()
    second_url = f"http://127.0.0.1:{second_port}"
    second = _start_runtime(second_port, environment)
    try:
        _wait_for_ready(second, second_url)
        restored = _api_json(
            second_url,
            f"/api/v2/entities/{ids['hero_id']}/mind?actor_id={ids['actor_id']}",
            token=token,
        )
        assert isinstance(restored, dict)
        assert restored["beliefs"][0]["value"] == "OPEN"
        assert float(restored["relationships"][0]["trust"]) == 12

        revised = _api_json(
            second_url,
            f"/api/v2/events/{second_event_id}/observe",
            token=token,
            method="POST",
            payload={
                "observer_actor_id": ids["actor_id"],
                "observer_entity_id": ids["hero_id"],
                "importance": 0.9,
            },
        )
        assert isinstance(revised, dict)
        assert revised["belief_revision"]["active_beliefs"][0]["value"] == "CLOSED"
        assert revised["belief_revision"]["superseded_beliefs"][0][
            "contradicted_by_event_id"
        ] == str(second_event_id)

        accumulated = _api_json(
            second_url,
            f"/api/v2/entities/{ids['hero_id']}/relationships",
            token=token,
            method="POST",
            payload={
                "target_entity_id": target_entity_id,
                "source_event_id": str(second_event_id),
                "event_type": "kept_promise",
            },
        )
        assert isinstance(accumulated, dict)
        assert accumulated["before"]["trust"] == 12
        assert accumulated["after"]["trust"] == 24
        assert accumulated["after"]["respect"] == 8

        durable = _api_json(
            second_url,
            f"/api/v2/entities/{ids['hero_id']}/mind?actor_id={ids['actor_id']}",
            token=token,
        )
        assert isinstance(durable, dict)
        assert len(durable["observations"]) == 2
        assert len(durable["memories"]) == 2
        assert len(durable["beliefs"]) == 2
        assert len(durable["relationship_changes"]) == 2
        active = [
            belief for belief in durable["beliefs"] if belief["contradicted_by_event_id"] is None
        ]
        assert len(active) == 1
        assert active[0]["value"] == "CLOSED"
        assert float(durable["relationships"][0]["trust"]) == 24
    finally:
        _stop_runtime(second)
