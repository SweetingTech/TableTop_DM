"""Unattended acceptance through the production worker processes and command ledger."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import pytest

from kernel.api.app import create_app
from tests.integration.test_clean_boot import _stop_runtime
from tests.integration.test_world_time import clock_path, prepare
from tests.unit.cognition.test_dialogue_generation import dialogue_server
from tests.unit.kernel.test_character_binding_api import setup_bound_character
from tests.unit.kernel.test_speech_combat_behavior import provoke
from tests.unit.kernel.test_tactical_choices import resources
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
HORIZON = 12


@contextmanager
def campaign_workers(artifact_root):
    environment = {**os.environ, "TTDM_ARTIFACT_ROOT": str(artifact_root)}
    with ExitStack() as stack:
        workers = []
        for command in ("projector", "runner", "world-runner"):
            output = stack.enter_context(tempfile.TemporaryFile(mode="w+t", encoding="utf-8"))
            process = subprocess.Popen(
                [sys.executable, "main.py", command],
                cwd=ROOT,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            process.runtime_output = output
            stack.callback(_stop_runtime, process)
            workers.append(process)
        yield workers


def control(client, path, run):
    answer = client.get(path + "/control", query_string={"run_id": run})
    assert answer.status_code == 200, answer.get_json()
    return answer.get_json()["control"]


@pytest.mark.parametrize("provider_status", [200, 503], ids=["guided-speech", "provider-outage"])
def test_cast_talks_recovers_and_resumes_work_without_manual_actions(
    isolated_integration_stack, monkeypatch, tmp_path, provider_status
):
    monkeypatch.setenv("TTDM_DIALOGUE_MODE", "off")
    monkeypatch.setenv("TTDM_DELIBERATION_MODE", "off")
    app, (admin, wounded, card, wound_path, run, gardener, base) = prepare(
        isolated_integration_stack, monkeypatch, tmp_path
    )
    _, courier, courier_card, _, courier_path, _, _ = setup_bound_character(
        app,
        scope={
            "world_id": base["world_id"],
            "canonical_branch_id": base["branch_id"],
            "current_run_id": run,
        },
    )
    rival = admin.post(
        f"/api/v2/worlds/{base['world_id']}/entities",
        json={
            "world_id": base["world_id"],
            "branch_id": base["branch_id"],
            "entity_type": "NPC",
            "name": "Harbor rival",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {"x": 1, "y": 0, "hp": 12, "max_hp": 12, "damage_bonus": -10},
        },
    )
    assert rival.status_code == 201, rival.get_json()
    rival_id = rival.get_json()["entity_id"]
    resources(app, admin, base, card["entity_id"], hp=4, known_spells=("MEND",))
    resources(app, admin, base, rival_id)
    provoke(admin, base, rival_id, card, "harbor-rival-strike")

    def health(client, path, entity):
        scene = client.get(path + "/scene").get_json()
        return next(
            item["health"] for item in scene["perceived_entities"] if item["entity_id"] == entity
        )

    hurt = health(wounded, wound_path, card["entity_id"])
    assert 0 < hurt <= 4
    cue = "The tide will turn at the old quay. Will you carry word?"
    message = api_command(
        admin,
        {**base, "embodied_entity_id": gardener},
        "tabletop.dialogue.speak",
        {"text": cue, "volume": "LOUD"},
        "campaign-opening-cue",
    )["event"]
    for due, raining in ((2, True), (4, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"zone_id": "world", "due_seconds": due, "raining": raining},
            f"rain-at-{due}",
        )

    cast = ((wounded, wound_path), (courier, courier_path))
    for client, path in cast:
        handed = client.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 2,
                "interval_ms": 100,
                "idempotency_key": "run-unattended",
            },
        )
        assert handed.status_code == 200, handed.get_json()

    def answer(request):
        assert request["reply_to"]
        source = next(
            item for item in request["experiences"] if item["reference"] == request["reply_to"]
        )
        assert source["text"] == cue
        return {"text": "I will carry word to the quay.", "sources": [source["reference"]]}

    clock_url = clock_path(base)
    initial = admin.get(clock_url).get_json()["clock"]
    with dialogue_server(monkeypatch, answer, status=provider_status) as requests:
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": initial["epoch"],
                "executor_actor_id": initial["executor_actor_id"],
                "paused": False,
                "seconds_per_tick": 1,
                "until_seconds": HORIZON,
                "wall_time": datetime.now(UTC).isoformat(),
            },
            "begin-unattended-scene",
        )
        # After launch the test only reads state. The real processes submit every action and tick.
        for restart in (False, True):
            calls_before_start = len(requests)
            with campaign_workers(tmp_path) as workers:
                deadline = time.monotonic() + 35
                while True:
                    assert all(worker.poll() is None for worker in workers)
                    snapshot = admin.get(clock_url).get_json()
                    states = [control(client, path, run) for client, path in cast]
                    if snapshot["clock"]["paused"] and all(
                        row["mode"] == "PAUSED" for row in states
                    ):
                        break
                    assert time.monotonic() < deadline, (snapshot["clock"]["seconds"], states)
                    time.sleep(0.15)
                if restart:
                    time.sleep(0.7)
                    assert admin.get(clock_url).get_json() == snapshot
                    assert [control(client, path, run) for client, path in cast] == states
                    assert len(requests) == calls_before_start

        assert 1 <= len(requests) <= (1 if provider_status == 200 else 2)

    assert snapshot["clock"]["seconds"] == HORIZON
    assert [row["step"] for row in states] == [2, 2]
    assert all(row["last_error"] == "step_limit" and row["failures"] == 0 for row in states)
    assert health(wounded, wound_path, card["entity_id"]) > hurt
    activity = snapshot["activities"][gardener]
    assert activity["status"] == "RUNNING" and activity["progress_seconds"] == HORIZON - 2

    with (
        psycopg2.connect(isolated_integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT event_type,embodied_entity_id,payload,causation_id,correlation_id,"
            "decision_trace_id "
            "FROM sim.events WHERE run_id=%s AND decision_trace_id IS NOT NULL ORDER BY seq_id",
            (run,),
        )
        events = cursor.fetchall()
        assert len(events) == 4
        wounded_events = [row for row in events if row[1] == card["entity_id"]]
        assert [row[0] for row in wounded_events] == [
            "tabletop.spatial.move",
            "tabletop.magic.invoke",
        ]
        assert wounded_events[1][2]["spell_id"] == "MEND"
        (utterance,) = [row for row in events if row[0] == "tabletop.dialogue.speak"]
        assert utterance[1] == courier_card["entity_id"]
        assert utterance[3:5] == (message["event_id"], message["correlation_id"])
        cursor.execute(
            "SELECT payload->'dialogue' FROM cognition.character_proposal_receipts "
            "WHERE decision_id=%s",
            (utterance[5],),
        )
        (receipt,) = cursor.fetchone()
        assert receipt["status"] == ("GENERATED" if provider_status == 200 else "FALLBACK")
        if provider_status == 200:
            assert utterance[2]["text"] == "I will carry word to the quay."
        cursor.execute(
            "SELECT result->'result'->>'seconds', result->'deltas' FROM sim.command_log "
            "WHERE run_id=%s AND command_type='tabletop.clock.tick' ORDER BY seq_id",
            (run,),
        )
        ticks = cursor.fetchall()
        assert [int(seconds) for seconds, _ in ticks] == list(range(1, HORIZON + 1))
        garden = {
            int(seconds): delta["values"]
            for seconds, deltas in ticks
            for delta in deltas
            if delta["projection"] == "tabletop.activities" and delta["entity_id"] == gardener
        }
        assert garden[2]["status"] == "WAITING" and garden[2]["reason"] == "RAIN"
        assert garden[4]["status"] == "RUNNING" and garden[4]["progress_seconds"] == 2

    restored = create_app(artifact_root=tmp_path).test_client()
    restored.set_cookie("ttdm_session", courier.get_cookie("ttdm_session").value)
    assert control(restored, courier_path, run) == states[1]
