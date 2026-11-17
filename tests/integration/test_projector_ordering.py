from __future__ import annotations

from dataclasses import replace

import pytest

from cognition.projector import WorldEventProjector
from kernel.database import transaction
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration


def test_branch_head_blocks_later_observations_until_retry(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    app, (admin, player, card, path, run, target, base) = prepare(stack, monkeypatch, tmp_path)
    first = WorldEventProjector(stack.database_url, worker_id="first")
    second = WorldEventProjector(stack.database_url, worker_id="second")
    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"

    def speak(message, key):
        return api_command(
            admin,
            {**base, "embodied_entity_id": target},
            "tabletop.dialogue.speak",
            {"text": message},
            key,
        )["event"]["event_id"]

    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        first_event = speak("The pass is open.", "ordered-first")
    (head,) = first._claim(1, topic=topic)
    assert str(head.event.event_id) == first_event
    second_event = speak("The pass is closed.", "ordered-second")
    event_ids = [first_event, second_event]

    def observations():
        with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT source_event_id FROM cognition.observations WHERE observer_entity_id=%s "
                "AND source_event_id=ANY(%s::uuid[])",
                (card["entity_id"], event_ids),
            )
            return {row[0] for row in cursor.fetchall()}

    assert second._claim(1, topic=topic) == ()
    assert observations() == set()
    decision = {"run_id": run, "idempotency_key": "after-ordering"}
    pending = player.post(path + "/character-proposals", json=decision)
    assert pending.status_code == 409 and pending.get_json()["error"] == "character_context_pending"
    movement = api_command(
        player,
        {**base, "embodied_entity_id": card["entity_id"]},
        "tabletop.spatial.move",
        {"dx": 0, "dy": -1},
        "player-moves-during-projection",
    )
    assert movement["result"]["accepted"]
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM cognition.human_movement_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
        )
        assert cursor.fetchone() == (0,)

    def project_then_interrupt(item):
        project(item)
        raise RuntimeError("fault after persisting an observation")

    project = first._project
    with monkeypatch.context() as patch:
        patch.setattr(first, "_project", project_then_interrupt)
        first._process_claim(head)
    assert observations() == {event_ids[0]}
    with monkeypatch.context() as patch:
        attempted = []
        patch.setattr(first, "_project", attempted.append)
        first._process_claim(replace(head, claim_owner="stale"))
        assert attempted == []
    assert second._claim(1, topic=topic) == ()
    assert player.post(path + "/character-proposals", json=decision).status_code == 409
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sim.outbox SET available_at=clock_timestamp() - interval '1 second' "
            "WHERE event_id=%s AND published_at IS NULL",
            (event_ids[0],),
        )
        assert cursor.rowcount == 1
    assert second.run_once(topic=topic) == 3
    assert observations() == set(event_ids)
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 6},
        "finish-move-recovery",
    )
    ready = player.post(path + "/character-proposals", json=decision)
    assert ready.status_code == 200, ready.get_json()
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_event_id,count(*) FROM cognition.observations "
            "WHERE observer_entity_id=%s "
            "AND source_event_id=ANY(%s::uuid[]) GROUP BY source_event_id",
            (card["entity_id"], event_ids),
        )
        assert dict(cursor.fetchall()) == dict.fromkeys(event_ids, 1)
