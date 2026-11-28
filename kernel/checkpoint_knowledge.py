from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cognition.relationships import RelationshipChangeRecord
from kernel.campaign_checkpoints import CampaignCheckpoint, CheckpointSection, FrozenComponent
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.postgres_campaign_checkpoints import CheckpointEvidence
from kernel.state import stable_hash

Row = dict[str, Any]


@dataclass(frozen=True)
class RestoredKnowledge:
    events: tuple[Row, ...]
    perceptions: tuple[Row, ...]
    subjective: dict[str, tuple[Row, ...]]
    event_origins: dict[str, str]

    @property
    def digest(self) -> str:
        return stable_hash(
            {
                "events": self.events,
                "perceptions": self.perceptions,
                "subjective": self.subjective,
                "event_origins": self.event_origins,
            }
        )


def restored_identity(branch: uuid.UUID, kind: str, source_identity: str | uuid.UUID) -> str:
    return str(uuid.uuid5(branch, f"{kind}:{source_identity}"))


def archived_rows(
    checkpoint: CampaignCheckpoint, section: CheckpointSection, table: str
) -> tuple[Row, ...]:
    component = checkpoint.sections[section]
    if not isinstance(component, FrozenComponent):
        raise CheckpointHoldConflict("checkpoint has an incompatible restoration section")
    rows = component.data.get(table)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CheckpointHoldConflict("checkpoint is missing a required restoration table")
    return tuple(row for row in rows if isinstance(row, dict))


def identifier_map(branch: uuid.UUID, kind: str, rows: Sequence[Row], key: str) -> dict[str, str]:
    identities: dict[str, str] = {}
    for row in rows:
        source = row.get(key)
        try:
            if (
                not isinstance(source, str)
                or str(uuid.UUID(source)) != source
                or source in identities
            ):
                raise ValueError("invalid row identity")
        except ValueError:
            raise CheckpointHoldConflict(
                "checkpoint has an invalid or duplicate identity"
            ) from None
        identities[source] = restored_identity(branch, kind, source)
    return identities


def remap_row(row: Row, keys: Mapping[str, Mapping[str, str]], required: frozenset[str]) -> Row:
    result = deepcopy(row)
    for field, replacements in keys.items():
        value = row.get(field)
        if value is None and field not in required:
            continue
        if not isinstance(value, str) or value not in replacements:
            raise CheckpointHoldConflict("checkpoint contains a reference outside the retained cut")
        result[field] = replacements[value]
    return result


def scoped_copy(
    row: Row,
    checkpoint: CampaignCheckpoint,
    branch: uuid.UUID,
    *,
    bodies: tuple[str, ...] = (),
) -> Row:
    if (row.get("world_id"), row.get("branch_id")) != (
        str(checkpoint.boundary.world_id),
        str(checkpoint.boundary.branch_id),
    ):
        raise CheckpointHoldConflict("checkpoint contains a row outside its archived scope")
    for key in bodies:
        value = row.get(key)
        if not isinstance(value, str) or value not in checkpoint.entities:
            raise CheckpointHoldConflict("checkpoint contains a reference to an unknown body")
    return {**row, "branch_id": str(branch)}


def restore_knowledge(
    checkpoint: CampaignCheckpoint,
    evidence: CheckpointEvidence,
    branch: uuid.UUID,
    run_ids: Mapping[str, str],
) -> RestoredKnowledge:
    """Prepare relational copies without creating new perceptions."""
    if checkpoint.boundary.branch_id == branch:
        raise CheckpointHoldConflict("restore requires a separate continuation branch")
    interactions = archived_rows(checkpoint, CheckpointSection.PENDING_WORK, "sim.interactions")
    traces = archived_rows(
        checkpoint, CheckpointSection.CHARACTER_RUNTIME, "cognition.decision_traces"
    )
    events = identifier_map(branch, "event", evidence.events, "event_id")
    event_keys = {
        "event_id": events,
        "run_id": run_ids,
        "parent_event_id": events,
        "causation_id": events,
        "interaction_id": identifier_map(branch, "interaction", interactions, "id"),
        "decision_trace_id": identifier_map(branch, "decision-trace", traces, "id"),
    }
    event_copies = []
    for row in evidence.events:
        body_fields = ("embodied_entity_id",) if row.get("embodied_entity_id") else ()
        scoped = scoped_copy(row, checkpoint, branch, bodies=body_fields)
        copy = remap_row(scoped, event_keys, frozenset({"event_id", "run_id"}))
        copy.pop("seq_id")
        # Historical events do not reserve request keys in the fresh execution.
        copy["idempotency_key"] = None
        event_copies.append(copy)
    perception_copies = tuple(
        remap_row(
            scoped_copy(row, checkpoint, branch, bodies=("observer_entity_id",)),
            {"event_id": events},
            frozenset({"event_id"}),
        )
        for row in evidence.perceptions
    )
    subjective = restore_subjective_rows(checkpoint, branch, events)
    return RestoredKnowledge(tuple(event_copies), perception_copies, subjective, events)


def restore_subjective_rows(
    checkpoint: CampaignCheckpoint, branch: uuid.UUID, events: Mapping[str, str]
) -> dict[str, tuple[Row, ...]]:
    def rows(name: str) -> tuple[Row, ...]:
        return archived_rows(checkpoint, CheckpointSection.MINDS, f"cognition.{name}")

    observations = rows("observations")
    beliefs = rows("beliefs")
    evidence = rows("belief_evidence")
    memories = rows("memories")
    changes = rows("relationship_changes")
    observation_ids = identifier_map(branch, "observation", observations, "id")
    belief_ids = identifier_map(branch, "belief", beliefs, "id")
    evidence_ids = identifier_map(branch, "belief-evidence", evidence, "id")

    def copies(
        records: tuple[Row, ...],
        bodies: tuple[str, ...],
        mapping: Mapping[str, Mapping[str, str]],
        required: frozenset[str] = frozenset(),
    ) -> tuple[Row, ...]:
        return tuple(
            remap_row(scoped_copy(row, checkpoint, branch, bodies=bodies), mapping, required)
            for row in records
        )

    relationship_changes = copies(
        changes,
        ("source_entity_id", "target_entity_id"),
        {"source_event_id": events},
        frozenset({"source_event_id"}),
    )
    for change in relationship_changes:
        # The normal reaction endpoint derives its retry key from the new causal scope.
        change["id"] = str(
            RelationshipChangeRecord.identity(
                world_id=checkpoint.boundary.world_id,
                branch_id=branch,
                source_entity_id=uuid.UUID(change["source_entity_id"]),
                target_entity_id=uuid.UUID(change["target_entity_id"]),
                source_event_id=uuid.UUID(change["source_event_id"]),
            )
        )

    return {
        "cognition.mind_states": copies(rows("mind_states"), ("entity_id",), {}),
        "cognition.observations": copies(
            observations,
            ("observer_entity_id",),
            {"id": observation_ids, "source_event_id": events},
            frozenset({"id", "source_event_id"}),
        ),
        "cognition.beliefs": copies(
            beliefs,
            ("entity_id",),
            {
                "id": belief_ids,
                "source_observation_id": observation_ids,
                "contradicted_by_event_id": events,
            },
            frozenset({"id"}),
        ),
        "cognition.belief_evidence": copies(
            evidence,
            ("entity_id",),
            {
                "id": evidence_ids,
                "belief_id": belief_ids,
                "source_observation_id": observation_ids,
                "claimed_origin_event_id": events,
                "parent_evidence_id": evidence_ids,
            },
            frozenset({"id", "source_observation_id"}),
        ),
        "cognition.memories": copies(
            memories,
            ("entity_id",),
            {
                "id": identifier_map(branch, "memory", memories, "id"),
                "source_event_id": events,
                "source_observation_id": observation_ids,
            },
            frozenset({"id", "source_event_id"}),
        ),
        "cognition.relationships": copies(
            rows("relationships"),
            ("source_entity_id", "target_entity_id"),
            {},
        ),
        "cognition.relationship_changes": relationship_changes,
    }
