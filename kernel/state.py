from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from kernel.contracts import BranchKind, StateDelta
from kernel.errors import BranchIsolationError


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class BranchState:
    world_id: uuid.UUID
    branch_id: uuid.UUID
    kind: BranchKind
    projections: dict[str, dict[str, Any]] = field(default_factory=dict)
    base_snapshot_hash: str | None = None
    version: int = 0

    def clone_for_trial(self, branch_id: uuid.UUID) -> BranchState:
        return BranchState(
            world_id=self.world_id,
            branch_id=branch_id,
            kind=BranchKind.TRIAL,
            projections=copy.deepcopy(self.projections),
            base_snapshot_hash=self.state_hash,
            version=0,
        )

    def working_copy(self) -> BranchState:
        """Return an isolated copy suitable for command evaluation."""
        return BranchState(
            world_id=self.world_id,
            branch_id=self.branch_id,
            kind=self.kind,
            projections=copy.deepcopy(self.projections),
            base_snapshot_hash=self.base_snapshot_hash,
            version=self.version,
        )

    @property
    def state_hash(self) -> str:
        return stable_hash(self.projections)

    def apply(self, delta: StateDelta) -> None:
        bucket = self.projections.setdefault(delta.projection, {})
        key = str(delta.entity_id or "singleton")
        if delta.operation == "DELETE":
            bucket.pop(key, None)
        elif delta.operation == "SET":
            bucket[key] = copy.deepcopy(delta.values)
        elif delta.operation == "MERGE":
            bucket.setdefault(key, {}).update(copy.deepcopy(delta.values))
        elif delta.operation == "INCREMENT":
            current = bucket.setdefault(key, {})
            for name, amount in delta.values.items():
                current[name] = current.get(name, 0) + amount


AtomicResult = TypeVar("AtomicResult")


class InMemoryStateStore:
    """Reference state store used by deterministic tests and local trial runs."""

    def __init__(self) -> None:
        self._branches: dict[uuid.UUID, BranchState] = {}
        self._receipts: dict[tuple[uuid.UUID, uuid.UUID, str], Any] = {}
        self._lock = threading.RLock()

    def add(self, state: BranchState) -> None:
        with self._lock:
            if state.branch_id in self._branches:
                raise BranchIsolationError(f"Branch already exists: {state.branch_id}")
            self._branches[state.branch_id] = state

    def get(self, branch_id: uuid.UUID) -> BranchState:
        with self._lock:
            try:
                return self._branches[branch_id]
            except KeyError as exc:
                raise BranchIsolationError(f"Unknown branch {branch_id}") from exc

    def all(self) -> tuple[BranchState, ...]:
        with self._lock:
            return tuple(self._branches[key] for key in sorted(self._branches, key=str))

    def execute_atomic(
        self,
        branch_id: uuid.UUID,
        idempotency_key: tuple[uuid.UUID, uuid.UUID, str],
        operation: Callable[[BranchState], AtomicResult],
    ) -> tuple[AtomicResult, bool]:
        """Evaluate against a copy and publish state and receipt as one operation.

        Handlers may freely inspect or even accidentally mutate the working state;
        exceptions cannot leak those mutations into the committed projection.
        Duplicate submissions return the original receipt.
        """
        with self._lock:
            if idempotency_key in self._receipts:
                return self._receipts[idempotency_key], True
            source = self.get(branch_id)
            working = source.working_copy()
            result = operation(working)
            source.projections = working.projections
            source.base_snapshot_hash = working.base_snapshot_hash
            source.version += 1
            self._receipts[idempotency_key] = result
            return result, False

    def create_trial(
        self, canonical_branch_id: uuid.UUID, trial_branch_id: uuid.UUID
    ) -> BranchState:
        with self._lock:
            canonical = self.get(canonical_branch_id)
            if canonical.kind is not BranchKind.CANONICAL:
                raise BranchIsolationError("Trials must be created from a canonical branch")
            trial = canonical.clone_for_trial(trial_branch_id)
            self.add(trial)
            return trial
