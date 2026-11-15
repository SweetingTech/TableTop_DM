from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from domains.tabletop.combat import attack
from kernel.application import SimulationApplication
from kernel.contracts import ActorKind, BranchKind, CommandProposal
from kernel.randomness import allocate_randomness

pytestmark = pytest.mark.unit


def arena(tmp_path, *, seed=0):
    app = SimulationApplication(tmp_path)
    world = app.create_world("Seed arena")
    run = next(iter(app.runs.values()))
    app.runs[run.run_id] = run.model_copy(update={"seed": seed})
    actor = app.create_actor(
        "fighter", ActorKind.HUMAN, set(), {"action.propose", "action.commit", "entity.act"}
    )
    bodies = [
        app.create_entity(
            world.world_id,
            run.branch_id,
            name,
            "NPC",
            {"x": x, "y": 0, "hp": 1000, "max_hp": 1000, "armor": 10},
            controller_actor_id=actor.actor_id,
        )
        for name, x in [("fighter", 0), ("target", 1)]
    ]
    actor = app.assign_control(world.world_id, actor.actor_id, bodies[0].entity_id)
    proposal = CommandProposal(
        world_id=world.world_id,
        branch_id=run.branch_id,
        run_id=run.run_id,
        actor_id=actor.actor_id,
        embodied_entity_id=bodies[0].entity_id,
        command_type="tabletop.combat.attack",
        parameters={"target_id": str(bodies[1].entity_id)},
        idempotency_key="attack",
        seed=41,
    )
    return app, actor, proposal


@pytest.mark.parametrize("run_seed", [0, 90210, None])
def test_run_seed_allocates_distinct_actions_and_retry_keeps_receipt(tmp_path, run_seed):
    app, actor, proposal = arena(tmp_path, seed=run_seed)
    before = app.states.get(proposal.branch_id).working_copy()
    first = app.bus.execute(proposal, actor)
    second = app.bus.execute(proposal.model_copy(update={"idempotency_key": "again"}), actor)
    a, b = first.result.result["randomness"], second.result.result["randomness"]
    assert a == allocate_randomness(run_seed, 1, proposal.command_type).model_dump()
    assert b == allocate_randomness(run_seed, 2, proposal.command_type).model_dump()
    assert a["action_seed"] != b["action_seed"]
    assert app.bus.execute(proposal.model_copy(update={"seed": -999}), actor) == first
    assert app.states.get(proposal.branch_id).version == 2
    # Independently re-evaluate mechanics from recorded provenance and pre-state.
    replayed = attack(proposal.model_copy(update={"seed": a["action_seed"]}), before)
    assert replayed.result == {k: v for k, v in first.result.result.items() if k != "randomness"}
    # The proposal/event seed remains policy provenance, never the mechanics seed.
    assert first.event.seed == 41
    assert all("randomness" not in str(p) for p in first.perceptions)


def test_caller_seed_cannot_select_the_roll(tmp_path):
    a, actor_a, request_a = arena(tmp_path / "a", seed=314)
    b, actor_b, request_b = arena(tmp_path / "b", seed=314)
    one = a.bus.execute(request_a.model_copy(update={"seed": 1}), actor_a)
    two = b.bus.execute(request_b.model_copy(update={"seed": 999}), actor_b)
    assert one.result.result["randomness"] == two.result.result["randomness"]
    assert one.result.result["attack_roll"] == two.result.result["attack_roll"]
    assert one.result.result["damage"] == two.result.result["damage"]


def test_invalid_action_does_not_advance_rng_sequence_or_state(tmp_path):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    target = state.projections["tabletop.entities"][request.parameters["target_id"]]
    target["x"] = 99
    position = state.projections["tabletop.spatial.positions"][request.parameters["target_id"]]
    position["x"] = 99
    before = state.working_copy()
    with pytest.raises(ValueError, match="reach"):
        app.bus.execute(request, actor)
    assert state.version == before.version and state.state_hash == before.state_hash
    target["x"] = 1
    position["x"] = 1
    receipt = app.bus.execute(request, actor)
    assert receipt.result.result["randomness"]["branch_sequence"] == 1


def test_concurrent_actions_allocate_under_the_commit_lock(tmp_path):
    app, actor, request = arena(tmp_path)

    def execute(index):
        return app.bus.execute(request.model_copy(update={"idempotency_key": str(index)}), actor)

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(execute, range(12)))
    proofs = [r.result.result["randomness"] for r in receipts]
    assert sorted(p["branch_sequence"] for p in proofs) == list(range(1, 13))
    assert len({p["action_seed"] for p in proofs}) == 12
    assert all(
        r.result.result["attack_roll"] == random.Random(p["action_seed"]).randint(1, 20)
        for r, p in zip(receipts, proofs, strict=True)
    )


def test_canonical_bus_fails_closed_without_trusted_run_reader(tmp_path):
    app, actor, proposal = arena(tmp_path)
    app.bus.run_seed_reader = None
    with pytest.raises(ValueError, match="trusted run"):
        app.bus.execute(proposal, actor)
    assert app.states.get(proposal.branch_id).version == 0
    # Explicit seed injection is restricted to the low-level trial harness.
    app.states.get(proposal.branch_id).kind = BranchKind.TRIAL
    assert "randomness" not in app.bus.execute(proposal, actor).result.result


def test_application_trial_uses_recorded_run_seed_and_replay(tmp_path):
    app, actor, proposal = arena(tmp_path)
    snapshot = app.create_branch_snapshot(proposal.branch_id)
    branch, run = app.create_trial(proposal.world_id, snapshot.snapshot_id, 72)
    trial = proposal.model_copy(update={"branch_id": branch.branch_id, "run_id": run.run_id})
    receipt = app.submit(trial)
    assert (
        receipt.result.result["randomness"]
        == allocate_randomness(72, 1, trial.command_type).model_dump()
    )
    assert app.replay(branch.branch_id).state_hash == receipt.state_hash
