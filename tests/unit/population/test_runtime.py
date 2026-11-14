from __future__ import annotations

import uuid

import pytest

from domains.tabletop.activities import ACTIVITIES
from kernel.branching import promote_consequences
from kernel.contracts import CommandProposal, StateDelta
from population.lifecycle import PopulationLifecycle
from population.models import PopulationLevel
from population.routines import ROUTINES
from population.runtime import HISTORY, MEMBERS, lifecycle_for
from tests.unit.kernel.test_world_time import advance, configure, reference, send

pytestmark = pytest.mark.unit


def runtime():
    app, ids = reference()
    configure(app, ids)
    body = uuid.uuid5(ids["world_id"], "routine-gardener")
    send(
        app,
        ids,
        "tabletop.entity.spawn",
        {
            "entity_id": str(body),
            "name": "Gardener",
            "entity_type": "villager",
            "public_state": {
                "hp": 100,
                "inventory": {"food": 3},
                "x": 50,
                "y": 0,
                "zone_id": "world",
            },
        },
        "gardener",
    )
    pool, persona = uuid.uuid5(body, "pool"), uuid.uuid5(body, "persona")
    source = PopulationLifecycle(ids["world_id"], ids["branch_id"])
    member = source.materialize(
        persona,
        profile={"occupation_sector": "agriculture"},
        persistent_state={"finances": {"coins": 999}, "hp": 999, "memories": ["PRIVATE_ORCHARD"]},
        world_step=17,
    )
    app.population_source_reader = lambda population, identity: source.get(identity)
    bound = send(
        app,
        ids,
        "tabletop.population.bind",
        {
            "population_id": str(pool),
            "entity_id": str(body),
            "source_member": member.model_dump(mode="json"),
        },
        "bind",
    )
    send(
        app,
        ids,
        "tabletop.routine.configure",
        {
            "entity_id": str(body),
            "expected_version": 0,
            "work_seconds": 120,
            "rest_seconds": 60,
            "hunger_limit": 300,
            "fatigue_limit": 180,
        },
        "routine",
    )
    return app, ids, str(body), persona, source, bound


def state(app, ids):
    return app.states.get(ids["branch_id"])


def test_binding_has_one_body_and_never_copies_resources_or_private_metadata_to_receipt():
    app, ids, body, persona, source, receipt = runtime()
    current = state(app, ids)
    member = lifecycle_for(current, persona).get(persona)
    assert member.entity_id == uuid.UUID(body) and member.version == 2
    assert member.persistent_state == {"memories": ["PRIVATE_ORCHARD"]}
    assert current.projections["tabletop.entities"][body]["hp"] == 100
    assert "population_bindings" not in receipt.result.model_dump(mode="json")
    assert "PRIVATE_ORCHARD" not in str(receipt.event.model_dump(mode="json"))
    before = current.state_hash
    with pytest.raises(ValueError, match="each be bound once"):
        send(
            app,
            ids,
            "tabletop.population.bind",
            {
                "population_id": str(uuid.uuid4()),
                "entity_id": body,
                "source_member": source.get(persona).model_dump(mode="json"),
            },
            "duplicate",
        )
    assert state(app, ids).state_hash == before


def test_forged_source_snapshot_rejected_atomically():
    app, ids = reference()
    configure(app, ids)
    entity = next(iter(app.states.get(ids["branch_id"]).projections["tabletop.entities"]))
    source = PopulationLifecycle(ids["world_id"], ids["branch_id"])
    member = source.materialize(uuid.uuid4(), profile={}, world_step=0)
    app.population_source_reader = lambda pool, persona: member
    forged = member.model_copy(update={"persistent_state": {"memories": ["forged"]}})
    before = state(app, ids).state_hash
    with pytest.raises(ValueError, match="source changed"):
        send(
            app,
            ids,
            "tabletop.population.bind",
            {
                "population_id": str(uuid.uuid4()),
                "entity_id": entity,
                "source_member": forged.model_dump(mode="json"),
            },
            "forged",
        )
    assert state(app, ids).state_hash == before
    assert not state(app, ids).projections.get(MEMBERS)


def test_coarse_and_split_clock_advances_have_identical_routines_resources_and_history():
    outcomes = []
    for boundaries in ([1300], [30, 119, 120, 180, 299, 300, 302, 305, 600, 1000, 1300]):
        app, ids, body, persona, _, _ = runtime()
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        outcomes.append(
            {
                key: current.projections.get(key)
                for key in (MEMBERS, HISTORY, ROUTINES, ACTIVITIES, "tabletop.entities")
            }
        )
        canonical = current.projections["tabletop.entities"][body]
        assert canonical["meals_eaten"] == 3
        assert canonical["inventory"]["food"] == 0
        assert current.projections[ACTIVITIES][body]["reason"] == "NO_FOOD"
        assert app.replay(ids["branch_id"]).state_hash == current.state_hash
    assert outcomes[0] == outcomes[1]


def test_rain_and_lifecycle_changes_preserve_partial_work_and_single_output():
    app, ids, body, persona, _, _ = runtime()
    for due, raining in ((30, True), (90, False)):
        send(
            app,
            ids,
            "tabletop.weather.schedule",
            {"due_seconds": due, "zone_id": "world", "raining": raining},
            f"rain:{due}",
        )
    advance(app, ids, 40)
    first = state(app, ids).projections[ACTIVITIES][body]
    assert first["progress_seconds"] == 30 and first["reason"] == "RAIN"
    for level in ("ACTIVE", "MATERIALIZED"):
        member = lifecycle_for(state(app, ids), persona).get(persona)
        send(
            app,
            ids,
            "tabletop.population.level",
            {"persona_id": str(persona), "expected_version": member.version, "level": level},
            "level:" + level,
        )
        assert state(app, ids).projections[ACTIVITIES][body] == first
    receipt = advance(app, ids, 150)
    assert state(app, ids).projections[ACTIVITIES][body]["progress_seconds"] == 90
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 90
    assert advance(app, ids, 150) == receipt
    assert lifecycle_for(state(app, ids), persona).get(persona).persistent_state["memories"] == [
        "PRIVATE_ORCHARD"
    ]


def test_physical_relevance_uses_any_anchor_body_and_never_human_presence():
    app, ids, body, persona, _, _ = runtime()
    anchor = uuid.uuid5(uuid.UUID(body), "any-class-party-member")
    send(
        app,
        ids,
        "tabletop.entity.spawn",
        {
            "entity_id": str(anchor),
            "name": "Traveller",
            "entity_type": "unrestricted_party_member",
            "public_state": {"hp": 10, "x": 55},
        },
        "anchor",
    )
    send(
        app,
        ids,
        "tabletop.routine.configure",
        {"entity_id": body, "expected_version": 1, "relevance_anchors": [str(anchor)]},
        "anchors",
    )
    advance(app, ids, 10)
    assert lifecycle_for(state(app, ids), persona).get(persona).level == PopulationLevel.ACTIVE
    # Fixture relocation represents a canonical move between two clock transactions.
    state(app, ids).projections["tabletop.spatial.positions"][str(anchor)]["x"] = 100
    advance(app, ids, 20)
    assert (
        lifecycle_for(state(app, ids), persona).get(persona).level == PopulationLevel.MATERIALIZED
    )
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 20


def test_incapacitation_movement_and_manual_activity_ownership_are_explicit():
    app, ids, body, persona, _, _ = runtime()
    with pytest.raises(ValueError, match="disable"):
        send(app, ids, "tabletop.activity.start", {"entity_id": body, "kind": "REST"}, "manual")
    advance(app, ids, 20)
    state(app, ids).projections["tabletop.entities"][body]["hp"] = 0
    advance(app, ids, 50)
    assert state(app, ids).projections[ACTIVITIES][body]["reason"] == "INCAPACITATED"
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 20
    state(app, ids).projections["tabletop.entities"][body]["hp"] = 100
    state(app, ids).projections["tabletop.spatial.positions"][body]["x"] = 51
    advance(app, ids, 60)
    assert state(app, ids).projections[ACTIVITIES][body]["reason"] == "MOVED"
    send(
        app,
        ids,
        "tabletop.routine.configure",
        {"entity_id": body, "expected_version": 1, "enabled": False},
        "disable",
    )
    assert state(app, ids).projections[ACTIVITIES][body]["status"] == "CANCELLED"
    send(app, ids, "tabletop.activity.start", {"entity_id": body, "kind": "REST"}, "manual-again")


def test_trial_copy_keeps_bindings_local_without_rebinding_or_mutating_canonical():
    app, ids, body, persona, _, _ = runtime()
    advance(app, ids, 20)
    canonical = state(app, ids).state_hash
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    trial, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 42)
    trial_ids = {**ids, "branch_id": trial.branch_id, "run_id": run.run_id}
    configure(app, trial_ids)
    advance(app, trial_ids, 40)
    member = lifecycle_for(state(app, trial_ids), persona).get(persona)
    assert member.branch_id == trial.branch_id and member.entity_id == uuid.UUID(body)
    assert state(app, ids).state_hash == canonical
    assert state(app, trial_ids).projections["tabletop.entities"][body]["weeded_units"] == 40


def test_needs_interrupt_long_rain_wait_at_same_time_for_coarse_and_split_ticks():
    outcomes = []
    for boundaries in ([700], [30, 299, 300, 305, 400, 605, 700]):
        app, ids, body, persona, _, _ = runtime()
        send(
            app,
            ids,
            "tabletop.weather.schedule",
            {"due_seconds": 30, "zone_id": "world", "raining": True},
            "rain-all-day",
        )
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        outcomes.append(
            {
                key: current.projections.get(key)
                for key in (MEMBERS, HISTORY, ROUTINES, ACTIVITIES, "tabletop.entities")
            }
        )
        assert current.projections["tabletop.entities"][body]["meals_eaten"] == 2
        assert current.projections["tabletop.entities"][body]["weeded_units"] == 30
    assert outcomes[0] == outcomes[1]


def test_relevance_override_changes_version_even_when_level_is_unchanged():
    app, ids, body, persona, _, _ = runtime()
    member = lifecycle_for(state(app, ids), persona).get(persona)
    for relevance in ("MATERIALIZED", "AUTO", "MATERIALIZED"):
        receipt = send(
            app,
            ids,
            "tabletop.population.level",
            {
                "persona_id": str(persona),
                "expected_version": member.version,
                "level": "MATERIALIZED",
                "relevance": relevance,
            },
            f"override:{member.version}:{relevance}",
        )
        assert receipt.result.result["version"] == member.version + 1
        member = lifecycle_for(state(app, ids), persona).get(persona)
    with pytest.raises(ValueError, match="version changed"):
        send(
            app,
            ids,
            "tabletop.population.level",
            {"persona_id": str(persona), "expected_version": member.version - 1, "level": "ACTIVE"},
            "stale-override",
        )


@pytest.mark.parametrize("change", ["remove", "duplicate", "rebind", "resources"])
def test_promotion_cannot_bypass_population_binding(change):
    import copy

    app, ids, body, persona, _, _ = runtime()
    current = state(app, ids)
    row = copy.deepcopy(current.projections[MEMBERS][str(persona)])
    identity, operation = persona, "SET"
    if change == "remove":
        operation = "DELETE"
    elif change == "duplicate":
        identity = uuid.uuid4()
    elif change == "rebind":
        row["entity_id"] = str(uuid.uuid4())
    else:
        row["member"]["persistent_state"]["finances"] = {"coins": 1000000}
    proposal = CommandProposal(
        **ids,
        command_type="kernel.branch.promote",
        idempotency_key="bad-promotion",
        parameters={
            "source_branch_id": str(uuid.uuid4()),
            "expected_canonical_hash": current.state_hash,
            "review_note": "test guarded promotion",
            "deltas": [
                StateDelta(
                    projection=MEMBERS, operation=operation, entity_id=identity, values=row
                ).model_dump(mode="json")
            ],
        },
    )
    before = current.state_hash
    with pytest.raises(ValueError):
        promote_consequences(proposal, current)
    assert current.state_hash == before


def test_promotion_can_carry_trial_lifecycle_without_rebinding_source():
    app, ids, body, persona, _, _ = runtime()
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    trial, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 43)
    trial_ids = {**ids, "branch_id": trial.branch_id, "run_id": run.run_id}
    receipt = send(
        app,
        trial_ids,
        "tabletop.population.level",
        {"persona_id": str(persona), "expected_version": 2, "level": "ACTIVE"},
        "trial-level",
    )
    send(
        app,
        ids,
        "kernel.branch.promote",
        {
            "source_branch_id": str(trial.branch_id),
            "expected_canonical_hash": state(app, ids).state_hash,
            "review_note": "Reviewed lifecycle",
            "deltas": [delta.model_dump(mode="json") for delta in receipt.result.deltas],
        },
        "promote-level",
    )
    member = lifecycle_for(state(app, ids), persona).get(persona)
    assert member.level == PopulationLevel.ACTIVE
    assert member.branch_id == ids["branch_id"] and member.entity_id == uuid.UUID(body)
