# H3 verification of unshared testimony after a character joins

The code under test was the exact hosted revision `c47eddb87f6201d611183d96111a7ef56c7e74dd`.
It has the same Git tree `b7b2179b930b0b336f37c613e7ced133f7f160bc` as merged main
`66df949d9cc5bb723bbc307f782ebdc979e41dc7`. The reference and isolated PostgreSQL 16
runs used the same checked-out implementation. This supplemental local test was run
after the hosted gate. The [original H3 report](https://github.com/SweetingTech/TableTop_DM/blob/e70fd5778f825b3fc50bda49df55b21646b77993/docs/verification/section-h/ci-proof.md#h3--voluntary-movement-leadership-resources-and-testimony) covers travel, leadership, resources, hearing range, and the hosted gate.

1. The ferryman whispered about a blue lantern. The prospective member heard it,
   and the founder did not. The member was outside the party at that point.
2. The founder invited the member, the member consented, and the scene showed both
   in the same party. The member still had the old observation. The founder's scene
   and decision context did not contain it, and the founder still could not query
   the member's scene.
3. The member deliberately shared a different message with the founder. The founder
   received just that message. The blue-lantern testimony remained private.
4. A fresh PostgreSQL app restored both characters' perceptions. The founder retained
   the shared message and party membership but could not see the unshared observation.
   The member retained the unshared observation, and branch replay verified.

The focused command selected both cases. It reported:

```text
collected 3 items / 1 deselected / 2 selected
====================== 2 passed, 1 deselected in 17.01s =======================
```

Run this module from the repository root with a temporary isolated PostgreSQL stack,
`TTDM_INTEGRATION=1`, and `PYTHONPATH` set to the repository root.

```powershell
python -m pytest -c pyproject.toml -p tests.integration.conftest <saved-test-module> -m 'unit or integration' -v
```

```python
import pytest

from tests.integration.test_action_rules import player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_party_api import create_and_invite, party_command, party_result, party_scene
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import clock_game


UNSHARED = "There is a blue lantern beneath the alder."
SHARED = "Meet by the north-bank ferry."


def speak(admin, base, body, text, key):
    response = command(
        admin, base, {"entity_id": body}, "tabletop.dialogue.speak",
        {"text": text, "volume": "WHISPER"}, key,
    )
    assert response.status_code == 200, response.get_json()


def check_founder(player, path, resident_path, run, *, shared):
    scene = party_scene(player, path)
    assert UNSHARED not in str(scene)
    assert (SHARED in str(scene["recent_observations"])) is shared
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200, context.get_json()
    assert UNSHARED not in str(context.get_json())
    assert player.get(resident_path + "/scene").status_code == 403
    return scene


def testimony_stays_private(app, game):
    admin, player, card, path, run, resident, base = game
    founder = card["entity_id"]
    resident_path = path.removesuffix(founder) + resident
    response = admin.post(
        f"/api/v2/worlds/{base['world_id']}/entities",
        json={
            "world_id": base["world_id"],
            "branch_id": base["branch_id"],
            "name": "Ferryman",
            "entity_type": "NPC",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {"x": 2, "y": 0, "hp": 12, "max_hp": 12},
        },
    )
    assert response.status_code == 201, response.get_json()
    ferryman = response.get_json()["entity_id"]

    # The resident is at (1, 0), within whisper distance of the ferryman.
    # The founder is at (0, 0), outside that distance.
    speak(admin, base, ferryman, UNSHARED, "ferryman-secret")
    assert UNSHARED in str(party_scene(admin, resident_path)["recent_observations"])
    assert check_founder(player, path, resident_path, run, shared=False)["parties"] == []

    party_id, invitation = create_and_invite(game)
    advance_clock(admin, base, 12)
    joined = party_command(
        admin, base, resident, "respond", {"invitation_id": invitation, "accept": True}, "join",
    )
    assert party_result(joined)["kind"] == "JOINED"
    joined_scene = check_founder(player, path, resident_path, run, shared=False)
    assert joined_scene["parties"][0]["party_id"] == party_id
    assert joined_scene["parties"][0]["member_ids"] == [founder, resident]
    assert UNSHARED in str(party_scene(admin, resident_path)["recent_observations"])
    advance_clock(admin, base, 24)

    # The member deliberately shares one thing while keeping the earlier testimony private.
    speak(admin, base, resident, SHARED, "member-shares-only-the-meeting")
    check_founder(player, path, resident_path, run, shared=True)
    return player, path, resident_path, run, resident, base


@pytest.mark.unit
def test_membership_does_not_copy_unshared_testimony(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    testimony_stays_private(app, clock_game(app))


@pytest.mark.integration
def test_unshared_testimony_stays_private_after_postgres_restart(integration_stack, monkeypatch, tmp_path):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    player, path, resident_path, run, resident, base = testimony_stays_private(app, game)
    _, restored_player = player_after_restart(tmp_path, player)
    scene = check_founder(restored_player, path, resident_path, run, shared=True)
    assert resident in scene["parties"][0]["member_ids"]
    _, restarted_admin = fresh_client(tmp_path)
    assert UNSHARED in str(party_scene(restarted_admin, resident_path)["recent_observations"])
    replay = restarted_admin.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
```
