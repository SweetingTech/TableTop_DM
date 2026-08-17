from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from kernel.contracts import CommandProposal, CommandResult
from kernel.state import BranchState


class ReplayRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal: CommandProposal
    result: CommandResult
    expected_state_hash: str


class ReplayDivergence(RuntimeError):
    pass


class ReplayEngine:
    """Rebuild a projection from committed deterministic command results."""

    @staticmethod
    def replay(initial: BranchState, records: tuple[ReplayRecord, ...]) -> BranchState:
        state = initial.working_copy()
        for index, record in enumerate(records, start=1):
            for delta in record.result.deltas:
                state.apply(delta)
            state.version += 1
            if state.state_hash != record.expected_state_hash:
                raise ReplayDivergence(
                    f"Replay diverged after record {index} ({record.proposal.command_id})"
                )
        return state
