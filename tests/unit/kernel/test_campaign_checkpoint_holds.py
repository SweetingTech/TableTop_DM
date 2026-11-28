from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import clock_game

pytestmark = pytest.mark.unit


def hold_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/checkpoint-holds"


def player_speech(player, base, card, key):
    return command(
        player, base, card, "tabletop.dialogue.speak", {"text": "The ferry is ready."}, key
    )


def test_campaign_hold_fences_new_actions_but_preserves_existing_receipts(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, _, base = clock_game(app)
    entry = hold_path(base)
    data = {"request_id": str(uuid.uuid4())}
    before = player_speech(player, base, card, "spoken-before-checkpoint")
    assert before.status_code == 200, before.get_json()
    assert player.post(entry, json=data).status_code == 403

    assert admin.get(entry).get_json() == {"hold": None}
    frozen = admin.post(entry, json=data)
    assert frozen.status_code == 200, frozen.get_json()
    held = frozen.get_json()
    receipt = before.get_json()
    assert held["status"] == "READY"
    assert held["pending_events"] == 0
    assert held["hold"]["through_event_id"] == receipt["event"]["event_id"]
    assert held["hold"]["state_hash"] == receipt["state_hash"]
    assert admin.get(entry).get_json() == held
    assert admin.post(entry, json=data).get_json() == held
    assert admin.post(entry, json={"request_id": str(uuid.uuid4())}).status_code == 409

    repeat = player_speech(player, base, card, "spoken-before-checkpoint")
    assert repeat.status_code == 200 and repeat.get_json()["event"] == receipt["event"]
    blocked = player_speech(player, base, card, "speak-after-checkpoint")
    assert blocked.status_code == 409 and blocked.get_json()["error"] == "branch_checkpoint_held"
    handoff = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "HUMAN",
        "idempotency_key": "new-handoff-during-checkpoint",
    }
    frozen_control = player.post(path + "/control", json=handoff)
    assert frozen_control.status_code == 409
    assert frozen_control.get_json()["error"] == "branch_checkpoint_held"

    release = f"{entry}/{data['request_id']}/release"
    assert player.post(release).status_code == 403
    after = admin.post(release).get_json()
    assert after["status"] == "RELEASED"
    assert admin.post(release).get_json() == after
    assert admin.post(entry, json=data).get_json() == after
    assert admin.get(entry).get_json() == {"hold": None}
    assert player_speech(player, base, card, "speak-after-checkpoint").status_code == 200
