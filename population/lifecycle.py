from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any

from population.models import PopulationLevel, PopulationMember, PopulationTransition


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class PopulationLifecycle:
    """In-process reference lifecycle with immutable records and transition history."""

    PRESERVED_ON_DEACTIVATION = frozenset(
        {
            "beliefs",
            "memories",
            "relationships",
            "finances",
            "history",
        }
    )

    def __init__(
        self,
        world_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> None:
        if (world_id is None) != (branch_id is None):
            raise ValueError("world_id and branch_id must be supplied together")
        self.world_id = world_id
        self.branch_id = branch_id
        self._members: dict[uuid.UUID, PopulationMember] = {}
        self._history: list[PopulationTransition] = []

    @property
    def history(self) -> tuple[PopulationTransition, ...]:
        return tuple(self._history)

    def get(self, persona_id: uuid.UUID) -> PopulationMember:
        try:
            return self._members[persona_id]
        except KeyError as exc:
            raise KeyError(f"Unknown statistical persona {persona_id}") from exc

    def restore(
        self,
        members: Iterable[PopulationMember],
        transitions: Iterable[PopulationTransition],
    ) -> None:
        """Restore an exact durable lifecycle projection without inventing transitions."""
        restored_members = {member.persona_id: copy.deepcopy(member) for member in members}
        restored_history = sorted(
            (copy.deepcopy(item) for item in transitions), key=lambda item: item.sequence
        )
        if len(restored_history) != len({item.transition_id for item in restored_history}):
            raise ValueError("population transition identifiers must be unique")
        for member in restored_members.values():
            if self.world_id is not None and (
                member.world_id != self.world_id or member.branch_id != self.branch_id
            ):
                raise ValueError("restored member belongs to a different world branch")
        self._members = restored_members
        self._history = restored_history

    def register(self, persona_id: uuid.UUID, profile: dict[str, Any]) -> PopulationMember:
        if persona_id in self._members:
            existing = self._members[persona_id]
            if existing.profile != profile:
                raise ValueError("A registered persona profile cannot be replaced")
            return existing
        member = PopulationMember(
            persona_id=persona_id,
            level=PopulationLevel.STATISTICAL,
            world_id=self.world_id,
            branch_id=self.branch_id,
            profile=copy.deepcopy(profile),
        )
        self._members[persona_id] = member
        return member

    def materialize(
        self,
        persona_id: uuid.UUID,
        *,
        profile: dict[str, Any] | None = None,
        persistent_state: dict[str, Any] | None = None,
        world_step: int,
        world_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        reason: str = "relevance_threshold",
    ) -> PopulationMember:
        if persona_id not in self._members:
            if profile is None:
                raise KeyError("Lazy materialization requires the statistical profile")
            self.register(persona_id, profile)
        before = self.get(persona_id)
        if before.level is not PopulationLevel.STATISTICAL:
            raise ValueError(f"Cannot materialize a {before.level.value} persona")
        target_world_id = world_id or self.world_id
        target_branch_id = branch_id or self.branch_id
        if (target_world_id is None) != (target_branch_id is None):
            raise ValueError("world_id and branch_id must be supplied together")
        after = before.model_copy(
            update={
                "level": PopulationLevel.MATERIALIZED,
                "world_id": target_world_id,
                "branch_id": target_branch_id,
                "persistent_state": copy.deepcopy(persistent_state or {}),
                "active_state": {},
                "compressed_state": {},
                "version": before.version + 1,
                "world_step": world_step,
            }
        )
        return self._commit(before, after, world_step, reason)

    def activate(
        self,
        persona_id: uuid.UUID,
        *,
        active_state: dict[str, Any],
        world_step: int,
        reason: str = "entered_relevance_window",
    ) -> PopulationMember:
        before = self.get(persona_id)
        if before.level is not PopulationLevel.MATERIALIZED:
            raise ValueError(f"Cannot activate a {before.level.value} persona")
        after = before.model_copy(
            update={
                "level": PopulationLevel.ACTIVE,
                "active_state": copy.deepcopy(active_state),
                "version": before.version + 1,
                "world_step": world_step,
            }
        )
        return self._commit(before, after, world_step, reason)

    def deactivate(
        self,
        persona_id: uuid.UUID,
        *,
        world_step: int,
        compressed_state: dict[str, Any] | None = None,
        preserve_fields: frozenset[str] | None = None,
        reason: str = "left_relevance_window",
    ) -> PopulationMember:
        before = self.get(persona_id)
        if before.level is not PopulationLevel.ACTIVE:
            raise ValueError(f"Cannot deactivate a {before.level.value} persona")
        preserved = self.PRESERVED_ON_DEACTIVATION if preserve_fields is None else preserve_fields
        persistent = copy.deepcopy(before.persistent_state)
        for field in sorted(preserved):
            if field in before.active_state:
                persistent[field] = copy.deepcopy(before.active_state[field])
        persistent.update(copy.deepcopy(compressed_state or {}))
        after = before.model_copy(
            update={
                "level": PopulationLevel.MATERIALIZED,
                "persistent_state": persistent,
                "active_state": {},
                "compressed_state": copy.deepcopy(compressed_state or {}),
                "version": before.version + 1,
                "world_step": world_step,
            }
        )
        return self._commit(before, after, world_step, reason)

    def _commit(
        self,
        before: PopulationMember,
        after: PopulationMember,
        world_step: int,
        reason: str,
    ) -> PopulationMember:
        if world_step < 0:
            raise ValueError("world_step cannot be negative")
        prior_steps = [
            item.world_step for item in self._history if item.persona_id == before.persona_id
        ]
        if prior_steps and world_step < prior_steps[-1]:
            raise ValueError("world_step cannot move backward for a persona")
        sequence = len(self._history) + 1
        transition_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:population-transition:{before.persona_id}:{sequence}:"
            f"{before.level.value}:{after.level.value}:{world_step}:"
            f"{_hash(after.persistent_state)}:{_hash(after.active_state)}",
        )
        transition = PopulationTransition(
            transition_id=transition_id,
            sequence=sequence,
            persona_id=before.persona_id,
            world_id=after.world_id,
            branch_id=after.branch_id,
            lifecycle_version=after.version,
            from_level=before.level,
            to_level=after.level,
            reason=reason,
            world_step=world_step,
            persistent_state_hash=_hash(after.persistent_state),
            active_state_hash=_hash(after.active_state),
        )
        self._members[after.persona_id] = after
        self._history.append(transition)
        return after
