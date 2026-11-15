from __future__ import annotations

import json
import uuid

import psycopg2.extras

from kernel.application import (
    EntityRecord,
    RunRecord,
    SimulationApplication,
    WorldRecord,
)
from kernel.contracts import (
    Actor,
    ActorKind,
    BranchKind,
    CommandProposal,
    CommandResult,
    EventEnvelopeV2,
    RunKind,
)
from kernel.control import ControllerState
from kernel.database import transaction
from kernel.errors import BranchIsolationError
from kernel.perception_contracts import PerceptionGrant
from kernel.replay import ReplayRecord
from kernel.snapshots import SnapshotEntity, SnapshotManifest, artifact_path
from kernel.state import BranchState


def _uuid(value: object) -> uuid.UUID:
    """Normalize UUID columns for drivers that return textual values."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _optional_uuid(value: object | None) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


class PostgresControlPlane:
    """Durable metadata/projection adapter for the local application service."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.actor_id: uuid.UUID | None = None

    def sync(self, simulation: SimulationApplication) -> None:
        """Create missing metadata without ever overwriting canonical projections."""
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                for world in simulation.worlds.values():
                    cursor.execute(
                        """
                        INSERT INTO sim.worlds (id, slug, name, status, domain_packs)
                        VALUES (%s,%s,%s,%s,%s::text[])
                        ON CONFLICT (id) DO UPDATE SET
                          name = EXCLUDED.name, status = EXCLUDED.status,
                          domain_packs = EXCLUDED.domain_packs, updated_at = now()
                        """,
                        (
                            str(world.world_id),
                            world.slug,
                            world.name,
                            world.status,
                            list(world.domain_packs),
                        ),
                    )
                for state in simulation.states.all():
                    base_snapshot_id = simulation.branch_snapshot_ids.get(state.branch_id) or next(
                        (
                            snapshot.snapshot_id
                            for snapshot in simulation.snapshots.values()
                            if snapshot.world_id == state.world_id
                            and snapshot.state_hash == state.base_snapshot_hash
                        ),
                        None,
                    )
                    cursor.execute(
                        """
                        INSERT INTO sim.branches (
                          id, world_id, branch_kind, name, base_snapshot_id, status
                        ) VALUES (%s,%s,%s,%s,%s,'ACTIVE')
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(state.branch_id),
                            str(state.world_id),
                            state.kind.value,
                            "Canonical"
                            if state.kind.value == "CANONICAL"
                            else f"Trial {str(state.branch_id)[:8]}",
                            str(base_snapshot_id) if base_snapshot_id else None,
                        ),
                    )
                for actor in simulation.actors.values():
                    cursor.execute(
                        """
                        INSERT INTO sim.actors (id, actor_kind, display_name)
                        VALUES (%s,%s,%s)
                        ON CONFLICT (id) DO UPDATE SET
                          actor_kind = EXCLUDED.actor_kind,
                          display_name = EXCLUDED.display_name,
                          updated_at = now()
                        """,
                        (str(actor.actor_id), actor.kind.value, actor.display_name),
                    )
                for (world_id, actor_id), authority in simulation.world_authorities.items():
                    for role in authority.roles:
                        cursor.execute(
                            """
                            INSERT INTO sim.actor_roles (world_id, actor_id, role)
                            VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
                            """,
                            (str(world_id), str(actor_id), role),
                        )
                    for capability in authority.capabilities:
                        cursor.execute(
                            """
                            INSERT INTO sim.actor_capabilities (
                              world_id, actor_id, capability
                            ) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
                            """,
                            (str(world_id), str(actor_id), capability),
                        )
                # Hydration reorders world-scoped authorities. Preserve the established
                # service identity rather than borrowing another world's actor on resync.
                bootstrap_actor = next(
                    (
                        actor
                        for actor in simulation.world_authorities.values()
                        if {"action.commit", "action.propose"}.issubset(actor.capabilities)
                        and (self.actor_id is None or actor.actor_id == self.actor_id)
                    ),
                    None,
                )
                if bootstrap_actor is None:
                    raise RuntimeError(
                        "durable bootstrap requires an actor with action capabilities"
                    )
                self.actor_id = bootstrap_actor.actor_id
                cursor.execute(
                    "SELECT set_config('app.actor_id', %s, true)",
                    (str(bootstrap_actor.actor_id),),
                )
                for state in simulation.states.all():
                    cursor.execute(
                        """
                        INSERT INTO sim.branch_projections (
                          branch_id, world_id, version, state, state_hash
                        ) VALUES (%s,%s,%s,%s::jsonb,%s)
                        ON CONFLICT (branch_id) DO NOTHING
                        """,
                        (
                            str(state.branch_id),
                            str(state.world_id),
                            state.version,
                            json.dumps(state.projections, default=str),
                            state.state_hash,
                        ),
                    )
                for entity in simulation.entities.values():
                    cursor.execute(
                        """
                        INSERT INTO sim.entities (
                          id, world_id, branch_id, entity_type, name,
                          public_state, secret_state, controller_actor_id
                        ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                        ON CONFLICT (branch_id, id) DO NOTHING
                        """,
                        (
                            str(entity.entity_id),
                            str(entity.world_id),
                            str(entity.branch_id),
                            entity.entity_type,
                            entity.name,
                            json.dumps(entity.public_state, default=str),
                            json.dumps(entity.secret_state, default=str),
                            str(entity.controller_actor_id) if entity.controller_actor_id else None,
                        ),
                    )
                for run in simulation.runs.values():
                    cursor.execute(
                        """
                        INSERT INTO sim.runs (
                          id, world_id, branch_id, run_kind, status, seed, started_at
                        ) VALUES (%s,%s,%s,%s,'RUNNING',%s,%s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(run.run_id),
                            str(run.world_id),
                            str(run.branch_id),
                            run.kind.value,
                            run.seed,
                            run.started_at,
                        ),
                    )

    def persist_snapshot(
        self, manifest: SnapshotManifest, projection_version: int, *, cursor=None
    ) -> None:
        artifact_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"tabletop-dm:snapshot-artifact:{manifest.artifact_hash}"
        )
        path = artifact_path(manifest.artifact_uri)
        byte_size = path.stat().st_size if path.exists() else None
        if self.actor_id is None:
            raise RuntimeError("control plane must be synchronized before loading state")
        if cursor is None:
            with transaction(actor_id=self.actor_id, dsn=self.dsn) as connection:
                with connection.cursor() as own:
                    self.persist_snapshot(manifest, projection_version, cursor=own)
            return
        cursor.execute(
            """INSERT INTO artifacts.objects (
              id,world_id,branch_id,artifact_kind,uri,content_hash,media_type,byte_size,metadata
            ) VALUES (%s,%s,%s,'SNAPSHOT',%s,%s,'application/gzip',%s,'{}')
            ON CONFLICT (id) DO NOTHING""",
            (
                str(artifact_id),
                str(manifest.world_id),
                str(manifest.branch_id),
                manifest.artifact_uri,
                manifest.artifact_hash,
                byte_size,
            ),
        )
        cursor.execute(
            """INSERT INTO sim.snapshots (
              id,world_id,source_branch_id,through_event_seq,projection_version,state_hash,
              artifact_id,contract_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (
                str(manifest.snapshot_id),
                str(manifest.world_id),
                str(manifest.branch_id),
                manifest.through_event_seq,
                projection_version,
                manifest.state_hash,
                str(artifact_id),
                manifest.contract_version,
            ),
        )

    def capture_snapshot(self, simulation, world_id, branch_id, *, actor_id):
        """Freeze projection and entity metadata behind the command's branch fence."""
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT 1 FROM sim.actor_capabilities c JOIN sim.actors a ON a.id=c.actor_id "
                    "WHERE c.world_id=%s AND c.actor_id=%s AND c.capability='run.branch' "
                    "AND a.is_active FOR SHARE OF c,a",
                    (str(world_id), str(actor_id)),
                )
                if cursor.fetchone() is None:
                    raise PermissionError("snapshot requires current world branch authority")
                cursor.execute(
                    "SELECT id FROM sim.branches WHERE world_id=%s AND id=%s FOR UPDATE",
                    (str(world_id), str(branch_id)),
                )
                if cursor.fetchone() is None:
                    raise ValueError("snapshot branch does not belong to world")
                cursor.execute(
                    "SELECT state,version FROM sim.branch_projections WHERE world_id=%s "
                    "AND branch_id=%s FOR UPDATE",
                    (str(world_id), str(branch_id)),
                )
                projected = cursor.fetchone()
                if projected is None:
                    raise ValueError("snapshot projection is unavailable")
                cursor.execute(
                    "SELECT id,world_id,branch_id,entity_type,name,"
                    "controller_actor_id,secret_state "
                    "FROM sim.entities WHERE world_id=%s AND branch_id=%s ORDER BY id",
                    (str(world_id), str(branch_id)),
                )
                entities = {}
                for row in cursor.fetchall():
                    raw = dict(row)
                    raw["entity_id"] = raw.pop("id")
                    record = SnapshotEntity.model_validate(raw)
                    entities[str(record.entity_id)] = record.model_dump(mode="json")
                cursor.execute(
                    "SELECT count(*) AS n FROM sim.command_log WHERE world_id=%s AND branch_id=%s",
                    (str(world_id), str(branch_id)),
                )
                count = cursor.fetchone()
                if count is None:
                    raise RuntimeError("snapshot event count is unavailable")
                manifest = simulation.snapshot_store.create(
                    world_id,
                    branch_id,
                    int(count["n"]),
                    dict(projected["state"]),
                    entities=entities,
                )
                self.persist_snapshot(manifest, int(projected["version"]), cursor=cursor)
        simulation.snapshots[manifest.snapshot_id] = manifest
        return manifest

    def persist_trial(self, simulation, branch, run, snapshot_id, *, actor_id):
        """Insert one isolated trial atomically; never resynchronize world grants."""
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM sim.actor_capabilities c JOIN sim.actors a ON a.id=c.actor_id "
                    "WHERE c.world_id=%s AND c.actor_id=%s AND c.capability='run.branch' "
                    "AND a.is_active FOR SHARE OF c,a",
                    (str(branch.world_id), str(actor_id)),
                )
                if cursor.fetchone() is None:
                    raise PermissionError("trial creation requires current world branch authority")
                cursor.execute(
                    "SELECT 1 FROM sim.snapshots WHERE world_id=%s AND id=%s",
                    (str(branch.world_id), str(snapshot_id)),
                )
                if cursor.fetchone() is None:
                    raise ValueError("trial snapshot is unavailable in this world")
                cursor.execute(
                    "INSERT INTO sim.branches "
                    "(id,world_id,branch_kind,name,base_snapshot_id,status) "
                    "VALUES (%s,%s,'TRIAL',%s,%s,'ACTIVE') ON CONFLICT(id) DO NOTHING",
                    (
                        str(branch.branch_id),
                        str(branch.world_id),
                        f"Trial {str(branch.branch_id)[:8]}",
                        str(snapshot_id),
                    ),
                )
                cursor.execute(
                    "SELECT world_id,base_snapshot_id FROM sim.branches WHERE id=%s",
                    (str(branch.branch_id),),
                )
                existing = cursor.fetchone()
                if existing is None or (_uuid(existing[0]), _uuid(existing[1])) != (
                    branch.world_id,
                    snapshot_id,
                ):
                    raise ValueError("trial lineage differs from the requested snapshot")
                cursor.execute(
                    "INSERT INTO sim.branch_projections "
                    "(branch_id,world_id,version,state,state_hash) "
                    "VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT(branch_id) DO NOTHING",
                    (
                        str(branch.branch_id),
                        str(branch.world_id),
                        branch.version,
                        json.dumps(branch.projections, default=str),
                        branch.state_hash,
                    ),
                )
                for (scope, _), entity in sorted(
                    simulation.entities.items(), key=lambda pair: str(pair[0])
                ):
                    if scope != branch.branch_id:
                        continue
                    cursor.execute(
                        "INSERT INTO sim.entities "
                        "(id,world_id,branch_id,entity_type,name,public_state,"
                        "secret_state,controller_actor_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) "
                        "ON CONFLICT(branch_id,id) DO NOTHING",
                        (
                            str(entity.entity_id),
                            str(entity.world_id),
                            str(scope),
                            entity.entity_type,
                            entity.name,
                            json.dumps(entity.public_state, default=str),
                            json.dumps(entity.secret_state, default=str),
                            str(entity.controller_actor_id) if entity.controller_actor_id else None,
                        ),
                    )
                cursor.execute(
                    "INSERT INTO sim.runs (id,world_id,branch_id,run_kind,status,seed,started_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (
                        str(run.run_id),
                        str(run.world_id),
                        str(run.branch_id),
                        run.kind.value,
                        run.status,
                        run.seed,
                        run.started_at,
                    ),
                )

    def hydrate(self, simulation: SimulationApplication) -> None:
        """Reconstruct durable control-plane metadata after bootstrap authorization."""
        if self.actor_id is None:
            raise RuntimeError("control plane must be synchronized before hydration")
        simulation.command_history.clear()
        simulation.replay_bases.clear()
        simulation.replay_offsets.clear()
        simulation.world_authorities.clear()
        branch_base_snapshot_ids: dict[uuid.UUID, uuid.UUID] = {}
        snapshot_projection_versions: dict[uuid.UUID, int] = {}
        with transaction(actor_id=self.actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT world.*, canonical.id AS canonical_branch_id
                    FROM sim.worlds world
                    JOIN sim.branches canonical
                      ON canonical.world_id = world.id
                     AND canonical.branch_kind = 'CANONICAL'
                    ORDER BY world.created_at, world.id
                    """
                )
                for row in cursor.fetchall():
                    world_id = _uuid(row["id"])
                    simulation.worlds[world_id] = WorldRecord(
                        world_id=world_id,
                        slug=row["slug"],
                        name=row["name"],
                        status=row["status"],
                        domain_packs=tuple(row["domain_packs"]),
                        canonical_branch_id=_uuid(row["canonical_branch_id"]),
                        created_at=row["created_at"],
                    )

                cursor.execute(
                    """
                    SELECT branch.id, branch.world_id, branch.branch_kind,
                           branch.base_snapshot_id, projection.version,
                           projection.state, snapshot.state_hash AS base_snapshot_hash
                    FROM sim.branches branch
                    JOIN sim.branch_projections projection
                      ON projection.world_id = branch.world_id
                     AND projection.branch_id = branch.id
                    LEFT JOIN sim.snapshots snapshot
                      ON snapshot.world_id = branch.world_id
                     AND snapshot.id = branch.base_snapshot_id
                    ORDER BY branch.created_at, branch.id
                    """
                )
                for row in cursor.fetchall():
                    branch_id = _uuid(row["id"])
                    world_id = _uuid(row["world_id"])
                    base_snapshot_id = _optional_uuid(row["base_snapshot_id"])
                    if base_snapshot_id is not None:
                        branch_base_snapshot_ids[branch_id] = base_snapshot_id
                    try:
                        state = simulation.states.get(branch_id)
                    except BranchIsolationError:
                        state = BranchState(
                            world_id=world_id,
                            branch_id=branch_id,
                            kind=BranchKind(row["branch_kind"]),
                        )
                        simulation.states.add(state)
                    state.kind = BranchKind(row["branch_kind"])
                    state.projections = dict(row["state"])
                    state.version = int(row["version"])
                    state.base_snapshot_hash = row["base_snapshot_hash"]
                    if row["base_snapshot_id"] is not None:
                        simulation.branch_snapshot_ids[branch_id] = _uuid(row["base_snapshot_id"])

                cursor.execute(
                    """
                    SELECT actor.id, actor.actor_kind, actor.display_name
                    FROM sim.actors actor
                    WHERE actor.is_active
                    ORDER BY actor.created_at, actor.id
                    """
                )
                actor_rows = list(cursor.fetchall())
                for row in actor_rows:
                    actor_id = _uuid(row["id"])
                    simulation.actors[actor_id] = Actor(
                        actor_id=actor_id,
                        kind=ActorKind(row["actor_kind"]),
                        display_name=row["display_name"],
                    )

                cursor.execute(
                    """
                    SELECT * FROM sim.entities ORDER BY world_id, branch_id, id
                    """
                )
                controlled: dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]] = {}
                for row in cursor.fetchall():
                    entity = EntityRecord(
                        entity_id=_uuid(row["id"]),
                        world_id=_uuid(row["world_id"]),
                        branch_id=_uuid(row["branch_id"]),
                        entity_type=row["entity_type"],
                        name=row["name"],
                        controller_actor_id=_optional_uuid(row["controller_actor_id"]),
                        public_state=dict(row["public_state"]),
                        secret_state=dict(row["secret_state"]),
                    )
                    simulation.entities[(entity.branch_id, entity.entity_id)] = entity
                    if entity.controller_actor_id is not None:
                        controlled.setdefault(
                            (entity.world_id, entity.controller_actor_id), set()
                        ).add(entity.entity_id)

                cursor.execute(
                    """
                    WITH associations AS (
                      SELECT world_id, actor_id FROM sim.actor_roles
                      UNION
                      SELECT world_id, actor_id FROM sim.actor_capabilities
                      UNION
                      SELECT world_id, controller_actor_id AS actor_id
                      FROM sim.entities WHERE controller_actor_id IS NOT NULL
                    )
                    SELECT association.world_id, actor.id, actor.actor_kind,
                           actor.display_name,
                           coalesce(array_agg(DISTINCT role.role)
                             FILTER (WHERE role.role IS NOT NULL), '{}') AS roles,
                           coalesce(array_agg(DISTINCT capability.capability)
                             FILTER (WHERE capability.capability IS NOT NULL), '{}')
                             AS capabilities
                    FROM associations association
                    JOIN sim.actors actor ON actor.id = association.actor_id
                    LEFT JOIN sim.actor_roles role
                      ON role.world_id = association.world_id
                     AND role.actor_id = association.actor_id
                    LEFT JOIN sim.actor_capabilities capability
                      ON capability.world_id = association.world_id
                     AND capability.actor_id = association.actor_id
                    WHERE actor.is_active
                    GROUP BY association.world_id, actor.id
                    ORDER BY association.world_id, actor.created_at, actor.id
                    """
                )
                for row in cursor.fetchall():
                    actor_id = _uuid(row["id"])
                    world_id = _uuid(row["world_id"])
                    actor = Actor(
                        actor_id=actor_id,
                        kind=ActorKind(row["actor_kind"]),
                        display_name=row["display_name"],
                        roles=frozenset(row["roles"]),
                        capabilities=frozenset(row["capabilities"]),
                        controlled_entity_ids=frozenset(
                            controlled.get((world_id, actor_id), set())
                        ),
                    )
                    simulation.world_authorities[(world_id, actor_id)] = actor

                cursor.execute("SELECT payload FROM cognition.controller_assignments")
                simulation.controller_states.clear()
                for row in cursor.fetchall():
                    controller = ControllerState.model_validate(row["payload"])
                    simulation.controller_states[controller.key] = controller
                cursor.execute("SELECT * FROM sim.runs ORDER BY created_at, id")
                for row in cursor.fetchall():
                    run_id = _uuid(row["id"])
                    simulation.runs[run_id] = RunRecord(
                        run_id=run_id,
                        world_id=_uuid(row["world_id"]),
                        branch_id=_uuid(row["branch_id"]),
                        kind=RunKind(row["run_kind"]),
                        status=row["status"],
                        seed=row["seed"],
                        started_at=row["started_at"] or row["created_at"],
                    )

                cursor.execute(
                    """
                    SELECT snapshot.*, artifact.uri, artifact.content_hash
                    FROM sim.snapshots snapshot
                    JOIN artifacts.objects artifact
                      ON artifact.world_id = snapshot.world_id
                     AND artifact.id = snapshot.artifact_id
                    ORDER BY snapshot.created_at, snapshot.id
                    """
                )
                for row in cursor.fetchall():
                    snapshot_id = _uuid(row["id"])
                    snapshot_projection_versions[snapshot_id] = int(row["projection_version"])
                    simulation.snapshots[snapshot_id] = SnapshotManifest(
                        snapshot_id=snapshot_id,
                        world_id=_uuid(row["world_id"]),
                        branch_id=_uuid(row["source_branch_id"]),
                        through_event_seq=int(row["through_event_seq"]),
                        state_hash=row["state_hash"],
                        artifact_uri=row["uri"],
                        artifact_hash=row["content_hash"],
                        contract_version=row["contract_version"],
                    )

                cursor.execute(
                    """
                    SELECT event.*, event.observed_by::text[] AS observed_by,
                           event.visible_to::text[] AS visible_to
                    FROM sim.events event
                    ORDER BY event.seq_id
                    """
                )
                event_fields = set(EventEnvelopeV2.model_fields)
                for row in cursor.fetchall():
                    payload = {name: row[name] for name in event_fields if name in row}
                    payload["observed_by"] = tuple(row["observed_by"] or ())
                    payload["visible_to"] = tuple(row["visible_to"] or ())
                    payload["domain_tags"] = tuple(row["domain_tags"] or ())
                    event = EventEnvelopeV2.model_validate(payload)
                    simulation.events[event.event_id] = event

                cursor.execute(
                    """
                    SELECT event_id, world_id, branch_id, observer_entity_id,
                           controller_actor_id, modalities, outcome, confidence,
                           allowed_payload_fields, hidden_payload_fields,
                           payload_overrides, reason_codes, resolver_version,
                           spatial_context_hash
                    FROM sim.event_perceptions
                    ORDER BY event_id, observer_entity_id
                    """
                )
                for row in cursor.fetchall():
                    grant = PerceptionGrant.model_validate(dict(row))
                    simulation.perceptions[(grant.event_id, grant.observer_entity_id)] = grant

                cursor.execute(
                    """
                    SELECT command.*, event.decision_trace_id,
                           event.persona_version, event.policy_version,
                           event.prompt_contract_version, event.model_version
                    FROM sim.command_log command
                    LEFT JOIN sim.events event
                      ON event.run_id = command.run_id
                     AND event.actor_id = command.actor_id
                     AND event.idempotency_key = command.idempotency_key
                    ORDER BY command.branch_id, command.seq_id
                    """
                )
                for row in cursor.fetchall():
                    branch_id = _uuid(row["branch_id"])
                    proposal = CommandProposal(
                        command_id=_uuid(row["command_id"]),
                        command_type=row["command_type"],
                        control_epoch=row["control_epoch"],
                        control_step=row["control_step"],
                        decision_authorship=row["decision_authorship"],
                        input_origin=row["input_origin"],
                        world_id=_uuid(row["world_id"]),
                        branch_id=branch_id,
                        run_id=_uuid(row["run_id"]),
                        interaction_id=_optional_uuid(row["interaction_id"]),
                        actor_id=_uuid(row["actor_id"]),
                        embodied_entity_id=_optional_uuid(row["embodied_entity_id"]),
                        parameters=dict(row["parameters"]),
                        idempotency_key=row["idempotency_key"],
                        correlation_id=_uuid(row["correlation_id"]),
                        causation_id=_optional_uuid(row["causation_id"]),
                        seed=row["seed"],
                        decision_trace_id=_optional_uuid(row["decision_trace_id"]),
                        persona_version=row["persona_version"],
                        policy_version=row["policy_version"],
                        prompt_contract_version=row["prompt_contract_version"],
                        model_version=row["model_version"],
                    )
                    simulation.command_history.setdefault(branch_id, []).append(
                        ReplayRecord(
                            proposal=proposal,
                            result=CommandResult.model_validate(row["result"]),
                            expected_state_hash=row["resulting_state_hash"],
                        )
                    )

        snapshots_by_branch: dict[uuid.UUID, list[SnapshotManifest]] = {}
        for manifest in simulation.snapshots.values():
            snapshots_by_branch.setdefault(manifest.branch_id, []).append(manifest)
        for state in simulation.states.all():
            history = simulation.command_history.get(state.branch_id, [])
            candidates = [
                manifest
                for manifest in snapshots_by_branch.get(state.branch_id, ())
                if manifest.through_event_seq <= len(history)
            ]
            offset = 0
            basis: SnapshotManifest | None
            if candidates:
                basis = max(
                    candidates,
                    key=lambda item: (item.through_event_seq, str(item.snapshot_id)),
                )
                offset = basis.through_event_seq
            else:
                basis_id = branch_base_snapshot_ids.get(state.branch_id)
                basis = simulation.snapshots.get(basis_id) if basis_id is not None else None
            if basis is not None:
                payload = simulation.snapshot_store.load(basis)
                simulation.replay_bases[state.branch_id] = BranchState(
                    world_id=state.world_id,
                    branch_id=state.branch_id,
                    kind=state.kind,
                    projections=dict(payload["projections"]),
                    version=(
                        0
                        if basis.branch_id != state.branch_id
                        else snapshot_projection_versions.get(
                            basis.snapshot_id, basis.through_event_seq
                        )
                    ),
                    base_snapshot_hash=state.base_snapshot_hash,
                )
                simulation.replay_offsets[state.branch_id] = offset
            elif history:
                # A pre-v2 or externally seeded ledger may not have a replay basis.
                # Preserve honest forward replay from the durable current boundary;
                # all clean v2 writes persist a basis before their first command.
                simulation.replay_bases[state.branch_id] = state.working_copy()
                simulation.replay_offsets[state.branch_id] = len(history)

    def load_projection(self, world_id: uuid.UUID, branch_id: uuid.UUID) -> tuple[int, dict]:
        if self.actor_id is None:
            raise RuntimeError("control plane must be synchronized before loading state")
        with transaction(actor_id=self.actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT version, state
                    FROM sim.branch_projections
                    WHERE world_id = %s AND branch_id = %s
                    """,
                    (str(world_id), str(branch_id)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(branch_id)
                return int(row[0]), dict(row[1])
