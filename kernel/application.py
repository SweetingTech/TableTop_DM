from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop import register_tabletop
from kernel.branching import BranchManager, promotion_definition
from kernel.command_bus import CommandBus, CommandReceipt
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal, RunKind
from kernel.errors import AuthorizationDenied, BranchIsolationError
from kernel.perception_contracts import PerceptionGrant
from kernel.replay import ReplayEngine, ReplayRecord
from kernel.snapshots import SnapshotManifest, SnapshotStore
from kernel.state import BranchState, InMemoryStateStore
from kernel.visibility import VisibilityPolicy


def stable_id(label: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"tabletop-dm:v2:{label}")


class WorldRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: uuid.UUID
    slug: str
    name: str
    status: str = "ACTIVE"
    domain_packs: tuple[str, ...] = ("tabletop",)
    canonical_branch_id: uuid.UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    kind: RunKind
    status: str = "ACTIVE"
    seed: int | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EntityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    entity_type: str
    name: str
    controller_actor_id: uuid.UUID | None = None
    public_state: dict[str, Any] = Field(default_factory=dict)
    secret_state: dict[str, Any] = Field(default_factory=dict)


class SimulationApplication:
    """Local-first application service around the domain-neutral kernel.

    PostgreSQL repositories expose the same constitutional command boundary for
    durable deployments.  This adapter keeps development, tests, and replay
    fixtures deterministic and dependency-free.
    """

    def __init__(self, artifact_root: Path | None = None) -> None:
        self.states = InMemoryStateStore()
        self.branches = BranchManager(self.states)
        self.bus = register_tabletop(CommandBus(self.states))
        self.bus.register(promotion_definition())
        self.worlds: dict[uuid.UUID, WorldRecord] = {}
        self.runs: dict[uuid.UUID, RunRecord] = {}
        self.actors: dict[uuid.UUID, Actor] = {}
        self.world_authorities: dict[tuple[uuid.UUID, uuid.UUID], Actor] = {}
        self.entities: dict[tuple[uuid.UUID, uuid.UUID], EntityRecord] = {}
        self.events: dict[uuid.UUID, Any] = {}
        self.perceptions: dict[tuple[uuid.UUID, uuid.UUID], PerceptionGrant] = {}
        self.command_history: dict[uuid.UUID, list[ReplayRecord]] = {}
        self.replay_bases: dict[uuid.UUID, BranchState] = {}
        self.replay_offsets: dict[uuid.UUID, int] = {}
        self.snapshot_store = SnapshotStore(artifact_root or Path("artifacts") / "snapshots")
        self.snapshots: dict[uuid.UUID, SnapshotManifest] = {}
        self.durable_repository: Any | None = None
        self.projection_loader: (
            Callable[[uuid.UUID, uuid.UUID], tuple[int, dict[str, Any]]] | None
        ) = None
        self.snapshot_persister: Callable[[SnapshotManifest, int], None] | None = None
        self.subjective_projector: Callable[[CommandReceipt], None] | None = None

    def configure_durable(
        self,
        repository: Any,
        projection_loader: Callable[[uuid.UUID, uuid.UUID], tuple[int, dict[str, Any]]],
        snapshot_persister: Callable[[SnapshotManifest, int], None] | None = None,
    ) -> None:
        self.durable_repository = repository
        self.projection_loader = projection_loader
        self.snapshot_persister = snapshot_persister

    def configure_subjective_projector(self, projector: Callable[[CommandReceipt], None]) -> None:
        self.subjective_projector = projector

    def create_world(
        self,
        name: str,
        slug: str | None = None,
        *,
        world_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> WorldRecord:
        slug = slug or re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        if not slug:
            raise ValueError("world slug cannot be empty")
        if any(world.slug == slug for world in self.worlds.values()):
            raise ValueError(f"world slug already exists: {slug}")
        world_id = world_id or uuid.uuid4()
        branch_id = branch_id or uuid.uuid4()
        self.branches.create_world(
            world_id,
            branch_id,
            {
                "tabletop.entities": {},
                "tabletop.obstacles": {},
                "tabletop.spatial.positions": {},
                "tabletop.spatial.zones": {},
                "tabletop.spatial.portals": {},
                "tabletop.spatial.occluders": {},
                "tabletop.quests": {},
                "tabletop.reputation": {},
            },
        )
        world = WorldRecord(
            world_id=world_id,
            slug=slug,
            name=name,
            canonical_branch_id=branch_id,
        )
        self.worlds[world_id] = world
        run_id = stable_id(f"run:{world_id}:live")
        self.runs[run_id] = RunRecord(
            run_id=run_id,
            world_id=world_id,
            branch_id=branch_id,
            kind=RunKind.LIVE,
        )
        return world

    def create_actor(
        self,
        display_name: str,
        kind: ActorKind,
        roles: set[str],
        capabilities: set[str],
        controlled_entity_ids: set[uuid.UUID] | None = None,
        actor_id: uuid.UUID | None = None,
        world_id: uuid.UUID | None = None,
    ) -> Actor:
        identity = Actor(
            actor_id=actor_id or uuid.uuid4(),
            display_name=display_name,
            kind=kind,
        )
        self.actors[identity.actor_id] = identity
        if world_id is None:
            if roles or capabilities or controlled_entity_ids:
                if len(self.worlds) != 1:
                    raise ValueError("world_id is required for scoped actor authority")
                world_id = next(iter(self.worlds))
            else:
                return identity
        return self.grant_authority(
            world_id,
            identity.actor_id,
            roles=roles,
            capabilities=capabilities,
            controlled_entity_ids=controlled_entity_ids or set(),
        )

    def grant_authority(
        self,
        world_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        roles: set[str] | frozenset[str],
        capabilities: set[str] | frozenset[str],
        controlled_entity_ids: set[uuid.UUID] | frozenset[uuid.UUID] = frozenset(),
    ) -> Actor:
        if world_id not in self.worlds:
            raise KeyError(world_id)
        identity = self.actors[actor_id]
        authority = identity.model_copy(
            update={
                "roles": frozenset(roles),
                "capabilities": frozenset(capabilities),
                "controlled_entity_ids": frozenset(controlled_entity_ids),
            }
        )
        self.world_authorities[(world_id, actor_id)] = authority
        return authority

    def authority(self, world_id: uuid.UUID, actor_id: uuid.UUID) -> Actor:
        try:
            return self.world_authorities[(world_id, actor_id)]
        except KeyError as exc:
            raise AuthorizationDenied("Actor has no authority in this world") from exc

    def authorities_for_world(self, world_id: uuid.UUID) -> tuple[Actor, ...]:
        return tuple(
            authority
            for (authority_world_id, _), authority in self.world_authorities.items()
            if authority_world_id == world_id
        )

    def assign_control(
        self, world_id: uuid.UUID, actor_id: uuid.UUID, entity_id: uuid.UUID
    ) -> Actor:
        authority = self.authority(world_id, actor_id)
        updated = authority.model_copy(
            update={
                "controlled_entity_ids": authority.controlled_entity_ids | frozenset({entity_id})
            }
        )
        self.world_authorities[(world_id, actor_id)] = updated
        return updated

    def create_run(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        kind: RunKind,
        *,
        seed: int | None = None,
        run_id: uuid.UUID | None = None,
    ) -> RunRecord:
        branch = self.states.get(branch_id)
        if branch.world_id != world_id:
            raise ValueError("branch does not belong to world")
        record = RunRecord(
            run_id=run_id or uuid.uuid4(),
            world_id=world_id,
            branch_id=branch_id,
            kind=kind,
            seed=seed,
        )
        if record.run_id in self.runs:
            raise ValueError("run already exists")
        self.runs[record.run_id] = record
        return record

    def create_entity(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        name: str,
        entity_type: str,
        public_state: dict[str, Any],
        *,
        secret_state: dict[str, Any] | None = None,
        controller_actor_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        project: bool = True,
    ) -> EntityRecord:
        branch = self.states.get(branch_id)
        if branch.world_id != world_id:
            raise ValueError("branch does not belong to world")
        entity = EntityRecord(
            entity_id=entity_id or uuid.uuid4(),
            world_id=world_id,
            branch_id=branch_id,
            entity_type=entity_type,
            name=name,
            controller_actor_id=controller_actor_id,
            public_state=public_state,
            secret_state=secret_state or {},
        )
        self.entities[(branch_id, entity.entity_id)] = entity
        if controller_actor_id is not None:
            self.assign_control(world_id, controller_actor_id, entity.entity_id)
        if project:
            branch.projections.setdefault("tabletop.entities", {})[str(entity.entity_id)] = {
                "name": name,
                "entity_type": entity_type,
                **public_state,
            }
            branch.projections.setdefault("tabletop.spatial.positions", {})[
                str(entity.entity_id)
            ] = {
                "entity_id": str(entity.entity_id),
                "zone_id": public_state.get("zone_id", "world"),
                "x": int(public_state.get("x", 0)),
                "y": int(public_state.get("y", 0)),
                "z": int(public_state.get("z", 0)),
                "facing": public_state.get("facing"),
            }
            branch.projections.setdefault("tabletop.sensory_profiles", {})[
                str(entity.entity_id)
            ] = {
                "controller_actor_id": (str(controller_actor_id) if controller_actor_id else None),
                "hearing_acuity": float(public_state.get("hearing_acuity", 1.0)),
                "sight_acuity": float(public_state.get("sight_acuity", 1.0)),
                "deafened": bool(public_state.get("deafened", False)),
                "blinded": bool(public_state.get("blinded", False)),
                "invisible": bool(public_state.get("invisible", False)),
            }
        return entity

    def submit(self, proposal: CommandProposal) -> CommandReceipt:
        branch = self.states.get(proposal.branch_id)
        if branch.world_id != proposal.world_id:
            raise ValueError("proposal branch does not belong to world")
        run = self.runs.get(proposal.run_id)
        if run is None or (run.world_id, run.branch_id) != (
            proposal.world_id,
            proposal.branch_id,
        ):
            raise ValueError("proposal run does not belong to world branch")
        actor = self.authority(proposal.world_id, proposal.actor_id)
        if proposal.command_type == "tabletop.entity.spawn":
            entity_id = uuid.UUID(str(proposal.parameters.get("entity_id")))
            if (proposal.branch_id, entity_id) in self.entities:
                raise ValueError("entity already exists in this branch")
            controller_id = proposal.parameters.get("controller_actor_id")
            if controller_id is not None:
                self.authority(proposal.world_id, uuid.UUID(str(controller_id)))
        if proposal.branch_id not in self.replay_bases:
            state = self.states.get(proposal.branch_id)
            history_length = len(self.command_history.get(proposal.branch_id, ()))
            self.replay_bases[proposal.branch_id] = state.working_copy()
            self.replay_offsets[proposal.branch_id] = history_length
            if self.snapshot_persister is not None:
                manifest = self.create_branch_snapshot(proposal.branch_id)
                self.snapshot_persister(manifest, state.version)
        if self.durable_repository is None:
            receipt = self.bus.execute(proposal, actor)
        else:
            receipt = self.durable_repository.execute(
                proposal, actor, self.bus.definition(proposal.command_type)
            )
            if self.projection_loader is None:
                raise RuntimeError("durable projection loader is not configured")
            version, projections = self.projection_loader(proposal.world_id, proposal.branch_id)
            committed = self.states.get(proposal.branch_id)
            committed.projections = projections
            committed.version = version
        if receipt.event.event_id not in self.events:
            if receipt.result.accepted:
                for mutation in receipt.result.entity_mutations:
                    key = (proposal.branch_id, mutation.entity_id)
                    expected = EntityRecord(
                        entity_id=mutation.entity_id,
                        world_id=proposal.world_id,
                        branch_id=proposal.branch_id,
                        entity_type=mutation.entity_type,
                        name=mutation.name,
                        controller_actor_id=mutation.controller_actor_id,
                        public_state=mutation.public_state,
                        secret_state=mutation.secret_state,
                    )
                    existing = self.entities.get(key)
                    if existing is None:
                        self.create_entity(
                            proposal.world_id,
                            proposal.branch_id,
                            mutation.name,
                            mutation.entity_type,
                            mutation.public_state,
                            secret_state=mutation.secret_state,
                            controller_actor_id=mutation.controller_actor_id,
                            entity_id=mutation.entity_id,
                            project=False,
                        )
                    elif existing != expected:
                        raise ValueError("idempotent entity mutation differs from entity")
            self.events[receipt.event.event_id] = receipt.event
            self.command_history.setdefault(proposal.branch_id, []).append(
                ReplayRecord(
                    proposal=proposal,
                    result=receipt.result,
                    expected_state_hash=receipt.state_hash,
                )
            )
        for grant in receipt.perceptions:
            self.perceptions[(grant.event_id, grant.observer_entity_id)] = grant
        if self.subjective_projector is not None:
            self.subjective_projector(receipt)
        return receipt

    def perception_grant(
        self, event_id: uuid.UUID, observer_entity_id: uuid.UUID
    ) -> PerceptionGrant | None:
        return self.perceptions.get((event_id, observer_entity_id))

    def perceptions_for_entity(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        observer_entity_id: uuid.UUID,
    ) -> tuple[PerceptionGrant, ...]:
        return tuple(
            sorted(
                (
                    grant
                    for grant in self.perceptions.values()
                    if grant.world_id == world_id
                    and grant.branch_id == branch_id
                    and grant.observer_entity_id == observer_entity_id
                ),
                key=lambda item: str(item.event_id),
            )
        )

    def create_snapshot(self, world_id: uuid.UUID) -> SnapshotManifest:
        world = self.worlds[world_id]
        return self.create_branch_snapshot(world.canonical_branch_id)

    def create_branch_snapshot(self, branch_id: uuid.UUID) -> SnapshotManifest:
        state = self.states.get(branch_id)
        through = len(self.command_history.get(branch_id, []))
        manifest = self.snapshot_store.create(state.world_id, branch_id, through, state.projections)
        self.snapshots[manifest.snapshot_id] = manifest
        return manifest

    def create_trial(
        self, world_id: uuid.UUID, snapshot_id: uuid.UUID, seed: int
    ) -> tuple[BranchState, RunRecord]:
        world = self.worlds[world_id]
        manifest = self.snapshots[snapshot_id]
        if manifest.world_id != world_id:
            raise ValueError("snapshot does not belong to world")
        branch_id = stable_id(f"trial:{snapshot_id}:{seed}")
        try:
            branch = self.states.get(branch_id)
        except BranchIsolationError:
            payload = self.snapshot_store.load(manifest)
            branch = BranchState(
                world_id=world_id,
                branch_id=branch_id,
                kind=BranchKind.TRIAL,
                projections=payload["projections"],
                base_snapshot_hash=manifest.state_hash,
            )
            self.states.add(branch)
        run_id = stable_id(f"run:{branch_id}:{seed}")
        run = self.runs.setdefault(
            run_id,
            RunRecord(
                run_id=run_id,
                world_id=world_id,
                branch_id=branch_id,
                kind=RunKind.EVALUATION,
                seed=seed,
            ),
        )
        canonical_entities = [
            entity
            for (entity_branch_id, _), entity in self.entities.items()
            if entity_branch_id == world.canonical_branch_id
        ]
        for entity in canonical_entities:
            projected = branch.projections.get("tabletop.entities", {}).get(
                str(entity.entity_id), entity.public_state
            )
            self.entities.setdefault(
                (branch_id, entity.entity_id),
                entity.model_copy(
                    update={
                        "branch_id": branch_id,
                        "public_state": {
                            key: value
                            for key, value in projected.items()
                            if key not in {"name", "entity_type"}
                        },
                    }
                ),
            )
        return branch, run

    def replay(self, branch_id: uuid.UUID) -> BranchState:
        base = self.replay_bases.get(branch_id)
        if base is None:
            return self.states.get(branch_id).working_copy()
        offset = self.replay_offsets.get(branch_id, 0)
        return ReplayEngine.replay(base, tuple(self.command_history.get(branch_id, ())[offset:]))

    def visible_events(self, actor_id: uuid.UUID) -> tuple[Any, ...]:
        visible = []
        for event in sorted(self.events.values(), key=lambda item: item.created_at):
            authority = self.world_authorities.get((event.world_id, actor_id))
            if authority is not None and VisibilityPolicy.event_for(event, authority) is not None:
                visible.append(event)
        return tuple(visible)

    def bootstrap_demo(self) -> dict[str, uuid.UUID]:
        if self.worlds:
            world = next(iter(self.worlds.values()))
            run = next(
                run
                for run in self.runs.values()
                if run.world_id == world.world_id and run.branch_id == world.canonical_branch_id
            )
            actor = next(iter(self.authorities_for_world(world.world_id)))
            return {
                "world_id": world.world_id,
                "branch_id": world.canonical_branch_id,
                "run_id": run.run_id,
                "actor_id": actor.actor_id,
            }
        world_id = stable_id("demo:world")
        branch_id = stable_id("demo:branch:canonical")
        world = self.create_world(
            "Eclipse Keep", "eclipse-keep", world_id=world_id, branch_id=branch_id
        )
        hero_id = stable_id("demo:entity:hero")
        actor = self.create_actor(
            "Local GM",
            ActorKind.HUMAN,
            {"GM", "PLAYER", "OBSERVER"},
            {
                "world.read",
                "world.read.all",
                "entity.control",
                "entity.act",
                "entity.create",
                "entity.read.secret",
                "action.propose",
                "action.commit",
                "run.branch",
                "metric.evaluate",
                "canonical.promote",
                "faction.manage",
                "divine.invoke",
                "mind.read.all",
                "mind.write.all",
            },
            {hero_id},
            stable_id("demo:actor:operator"),
            world.world_id,
        )
        self.create_entity(
            world_id,
            branch_id,
            "Aster Vale",
            "PLAYER_CHARACTER",
            {
                "x": 2,
                "y": 3,
                "hp": 24,
                "max_hp": 24,
                "armor": 14,
                "mana": 12,
                "gold": 40,
                "inventory": {"healing_herb": 2},
                "faction": "keepers",
                "conditions": [],
            },
            controller_actor_id=actor.actor_id,
            entity_id=hero_id,
        )
        self.create_entity(
            world_id,
            branch_id,
            "Ash Wolf",
            "NPC",
            {
                "x": 3,
                "y": 3,
                "hp": 11,
                "max_hp": 11,
                "armor": 11,
                "mana": 0,
                "gold": 0,
                "inventory": {},
                "faction": "wild",
                "conditions": [],
            },
            entity_id=stable_id("demo:entity:wolf"),
        )
        self.create_entity(
            world_id,
            branch_id,
            "Mara Venn",
            "NPC",
            {
                "x": 4,
                "y": 2,
                "hp": 18,
                "max_hp": 18,
                "armor": 10,
                "mana": 0,
                "gold": 120,
                "inventory": {"healing_herb": 20},
                "faction": "merchants",
                "conditions": [],
            },
            entity_id=stable_id("demo:entity:merchant"),
        )
        run = next(run for run in self.runs.values() if run.world_id == world.world_id)
        return {
            "world_id": world.world_id,
            "branch_id": branch_id,
            "run_id": run.run_id,
            "actor_id": actor.actor_id,
            "hero_id": hero_id,
        }
