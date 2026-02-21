import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator

from shared.schemas.enums import EventType


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_version: int = Field(ge=1, default=1)
    contract_version: int = Field(default=1)
    type: EventType
    campaign_id: uuid.UUID
    session_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    sender_principal_id: uuid.UUID
    sender_entity_id: Optional[uuid.UUID] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    visible_to: list[uuid.UUID]
    parent_event_id: Optional[uuid.UUID] = None
    domain_tags: list[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("visible_to")
    @classmethod
    def check_visible_to_not_empty(cls, v):
        if len(v) < 1:
            raise ValueError("visible_to must contain at least one principal ID")
        return v


class StateDelta(BaseModel):
    table: str
    operation: str
    entity_id: Optional[uuid.UUID] = None
    changes: dict[str, Any] = Field(default_factory=dict)
    domain_tags: list[str] = Field(default_factory=list)


class RollResult(BaseModel):
    dice: str
    rolls: list[int]
    modifier: int = 0
    total: int
    breakdown: str


class ToolCallPayload(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    deltas: list[StateDelta] = Field(default_factory=list)
    rolls: list[RollResult] = Field(default_factory=list)
