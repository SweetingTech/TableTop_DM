from __future__ import annotations

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class QuestProgressRequest(BaseModel):
    quest_id: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=160)
    amount: int = Field(default=1, ge=1, le=1_000)
    target: int = Field(default=1, ge=1, le=1_000_000)


class QuestProgressResult(BaseModel):
    quest_id: str
    objective: str
    progress: int = Field(ge=0)
    target: int = Field(ge=1)
    completed: bool


def advance(proposal: CommandProposal, state: BranchState) -> CommandResult:
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        raise ValueError("quest progress requires an embodied entity")
    request = QuestProgressRequest.model_validate(proposal.parameters)
    record = state.projections.get("tabletop.quests", {}).get(str(entity_id), {})
    quests = dict(record.get("quests", {}))
    quest = dict(quests.get(request.quest_id, {}))
    objectives = dict(quest.get("objectives", {}))
    value = min(request.target, int(objectives.get(request.objective, 0)) + request.amount)
    objectives[request.objective] = value
    quest.update({"objectives": objectives, "completed": value >= request.target})
    quests[request.quest_id] = quest
    return CommandResult(
        result={
            "quest_id": request.quest_id,
            "objective": request.objective,
            "progress": value,
            "target": request.target,
            "completed": quest["completed"],
        },
        deltas=(
            StateDelta(
                projection="tabletop.quests",
                operation="MERGE",
                entity_id=entity_id,
                values={"quests": quests},
            ),
        ),
        domain_tags=("tabletop", "quest", request.quest_id),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.quest.advance",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=advance,
        request_model=QuestProgressRequest,
        result_model=QuestProgressResult,
        requires_controlled_entity=True,
    )
