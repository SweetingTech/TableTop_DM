from __future__ import annotations

import uuid

import pytest

from domains.tabletop.character_state import CharacterBodyUnavailable, project_character_state
from domains.tabletop.portal import CharacterRecord
from kernel.contracts import BranchKind
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene
from tests.unit.kernel.test_tactical_choices import command, resources

pytestmark = pytest.mark.unit


def test_live_state_reads_body_without_overwriting_authored_card(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    endpoint = f"/api/v2/player/characters/{card['character_id']}/live-state"
    before = player.get(endpoint)
    assert before.status_code == 200, before.get_json()
    assert before.headers["Cache-Control"] == "no-store"
    assert before.get_json()["source"] == "KERNEL"
    resources(app, admin, base, card["entity_id"], hp=5, mana=8)
    sim = app.extensions["simulation"]
    projected = sim.states.get(uuid.UUID(base["branch_id"])).projections["tabletop.entities"][
        card["entity_id"]
    ]
    projected["dm_only"] = "HIDDEN_CANONICAL_NOTE"
    key = (uuid.UUID(base["branch_id"]), uuid.UUID(card["entity_id"]))
    sim.entities[key] = sim.entities[key].model_copy(
        update={"secret_state": {"plot": "HIDDEN_CANONICAL_NOTE"}}
    )
    healed = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {
            "spell_id": "MEND",
            "target_id": card["entity_id"],
        },
        "live-state-heal",
    )
    assert healed.status_code == 200
    view = player.get(endpoint).get_json()
    assert view["body"]["hp"] == 9 and view["body"]["mana"] == 6
    assert view["body"]["branch_id"] == base["branch_id"]
    assert view["body"]["projection_version"] > before.get_json()["body"]["projection_version"]
    authored = CharacterRecord.model_validate(
        next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
    )
    assert view["card_version"] == card["card_version"] == authored.card_version
    assert authored.current_hit_points == card["current_hit_points"]
    assert "SELF_PRIVATE_MAP" not in str(view) and "secret_state" not in str(view)
    assert "HIDDEN_CANONICAL_NOTE" not in str(view)


def test_unbound_card_is_explicit_authored_source(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    created = player.post("/api/v2/player/characters", json={"name": "Unbound"})
    assert created.status_code == 201, created.get_json()
    view = player.get(f"/api/v2/player/characters/{created.get_json()['character_id']}/live-state")
    assert view.status_code == 200 and view.get_json()["source"] == "AUTHORED"
    assert view.get_json()["body"] is None


@pytest.mark.parametrize("problem", ["missing_body", "missing_metadata", "foreign_world", "trial"])
def test_bound_unavailable_state_never_falls_back_to_card(monkeypatch, tmp_path, problem):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    sim = app.extensions["simulation"]
    record = CharacterRecord.model_validate(card)
    state = sim.states.get(uuid.UUID(base["branch_id"]))
    if problem == "missing_metadata":
        del sim.entities[(state.branch_id, uuid.UUID(card["entity_id"]))]
        assert (
            player.get(f"/api/v2/player/characters/{card['character_id']}/live-state").status_code
            == 409
        )
        return
    if problem == "missing_body":
        del state.projections["tabletop.entities"][card["entity_id"]]
        response = player.get(f"/api/v2/player/characters/{card['character_id']}/live-state")
        assert response.status_code == 409 and response.headers["Cache-Control"] == "no-store"
    elif problem == "foreign_world":
        state = state.working_copy()
        state.world_id = uuid.uuid4()
    else:
        state = state.working_copy()
        state.kind = BranchKind.TRIAL
    with pytest.raises(CharacterBodyUnavailable):
        project_character_state(record, state)


def test_owner_and_world_authority_are_both_required(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    other_admin, other_player, other_card, *_ = setup_scene(app)
    endpoint = f"/api/v2/player/characters/{card['character_id']}/live-state"
    forbidden = other_player.get(endpoint)
    assert forbidden.status_code == 403 and forbidden.headers["Cache-Control"] == "no-store"
    account = CharacterRecord.model_validate(card)
    response = admin.put(
        f"/api/v2/admin/users/{account.owner_user_id}/worlds/{base['world_id']}/roles",
        json={"roles": []},
    )
    assert response.status_code == 200
    assert player.get(endpoint).status_code == 403


def test_card_owner_without_body_control_cannot_borrow_other_world_dm_authority(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    sim = app.extensions["simulation"]
    record = CharacterRecord.model_validate(card)
    world_id, entity_id = uuid.UUID(base["world_id"]), uuid.UUID(card["entity_id"])
    key = (uuid.UUID(base["branch_id"]), entity_id)
    owner = sim.entities[key].controller_actor_id
    # Consistent reference fixture for a body whose control has moved elsewhere.
    sim.entities[key] = sim.entities[key].model_copy(
        update={"controller_actor_id": app.extensions["demo_ids"]["actor_id"]}
    )
    sim.controller_states = {
        k: v for k, v in sim.controller_states.items() if v.entity_id != entity_id
    }
    authority = sim.authority(world_id, owner)
    sim.grant_authority(
        world_id,
        owner,
        roles=authority.roles,
        capabilities=authority.capabilities,
        controlled_entity_ids=authority.controlled_entity_ids - {entity_id},
    )
    other = admin.post("/api/v2/worlds", json={"name": "Other live-state world"}).get_json()
    assert (
        admin.put(
            f"/api/v2/admin/users/{record.owner_user_id}/worlds/{other['world_id']}/roles",
            json={"roles": ["DM"]},
        ).status_code
        == 200
    )
    response = player.get(f"/api/v2/player/characters/{card['character_id']}/live-state")
    assert response.status_code == 403
