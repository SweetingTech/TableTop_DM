from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class ActionRandomness(BaseModel):
    """Private, replayable physical-action RNG provenance, separate from policy RNG."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str = "logical-action-rng-1.0.0"
    run_seed: int
    branch_sequence: int = Field(ge=1)
    action_seed: int = Field(ge=0, lt=2**63)


def allocate_randomness(run_seed: int | None, sequence: int, command_type: str) -> ActionRandomness:
    # Legacy unseeded runs have the same explicit, deterministic zero baseline.
    seed = 0 if run_seed is None else run_seed
    encoded = json.dumps(
        ["logical-action-rng-1.0.0", seed, sequence, command_type], separators=(",", ":")
    ).encode("utf-8")
    return ActionRandomness(
        run_seed=seed,
        branch_sequence=sequence,
        action_seed=int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") % (2**63),
    )
