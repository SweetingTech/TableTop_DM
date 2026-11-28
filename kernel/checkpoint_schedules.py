from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal

import psycopg2.errors
from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from kernel.checkpoint_holds import CheckpointHoldConflict, require_checkpoint_open
from kernel.database import transaction
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints

ScheduleLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ScheduleEventType = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=120)
]


class CheckpointRuleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: ScheduleLabel
    interval_seconds: int | None = Field(default=None, ge=1, le=2_592_000)
    event_types: tuple[ScheduleEventType, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_trigger(self) -> CheckpointRuleSettings:
        if self.interval_seconds is None and not self.event_types:
            raise ValueError("a checkpoint rule needs an interval or an event type")
        if len(set(self.event_types)) != len(self.event_types):
            raise ValueError("checkpoint event types must be unique")
        return self


class CheckpointRuleRequest(CheckpointRuleSettings):
    rule_id: uuid.UUID
    expected_rule_id: uuid.UUID | None = None


class CheckpointRule(CheckpointRuleSettings):
    rule_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    operator_actor_id: uuid.UUID
    anchor_seconds: int = Field(ge=0)
    active: bool
    created_at: AwareDatetime


class ScheduledCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    world_id: uuid.UUID
    branch_id: uuid.UUID
    request_id: uuid.UUID
    operator_actor_id: uuid.UUID
    label: ScheduleLabel
    cause: Literal["CLOCK", "EVENT"]
    source_event_id: uuid.UUID


class PostgresCheckpointSchedules:
    """Persistent operator rules and recovery of the exact held archive requests."""

    def __init__(
        self, dsn: str, archives: PostgresCampaignCheckpoints, machine_actor: uuid.UUID
    ) -> None:
        self.dsn = dsn
        self.archives = archives
        self.holds = archives.holds
        self.machine_actor = machine_actor
        self._retry_after: dict[uuid.UUID, float] = {}

    @staticmethod
    def _active_rule(cursor: RealDictCursor, scope: tuple[str, str]) -> CheckpointRule | None:
        cursor.execute(
            "SELECT * FROM sim.campaign_checkpoint_rules "
            "WHERE (world_id,branch_id)=(%s,%s) AND active",
            scope,
        )
        row = cursor.fetchone()
        return CheckpointRule.model_validate(row) if row else None

    def read(self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID) -> CheckpointRule | None:
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.holds.authorize(cursor, world, actor, private=True)
                self.holds._require_branch(cursor, world, branch)
                return self._active_rule(cursor, (str(world), str(branch)))

    def configure(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request: CheckpointRuleRequest
    ) -> CheckpointRule:
        scope = (str(world), str(branch))
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.holds.authorize(cursor, world, actor, private=True)
                self.holds._require_branch(cursor, world, branch, lock=True)
                cursor.execute(
                    "SELECT * FROM sim.campaign_checkpoint_rules "
                    "WHERE (world_id,branch_id,rule_id)=(%s,%s,%s)",
                    (*scope, str(request.rule_id)),
                )
                existing = cursor.fetchone()
                if existing:
                    rule = CheckpointRule.model_validate(existing)
                    if (
                        rule.operator_actor_id,
                        rule.label,
                        rule.interval_seconds,
                        rule.event_types,
                    ) != (
                        actor,
                        request.label,
                        request.interval_seconds,
                        tuple(sorted(request.event_types)),
                    ):
                        raise CheckpointHoldConflict(
                            "checkpoint schedule identifier was already used"
                        )
                    return rule
                require_checkpoint_open(cursor, world, branch)
                previous = self._active_rule(cursor, scope)
                if (previous.rule_id if previous else None) != request.expected_rule_id:
                    raise CheckpointHoldConflict("the active checkpoint schedule changed")
                if previous:
                    cursor.execute(
                        "UPDATE sim.campaign_checkpoint_rules SET active=false WHERE rule_id=%s",
                        (str(previous.rule_id),),
                    )
                cursor.execute(
                    """INSERT INTO sim.campaign_checkpoint_rules
                      (rule_id,world_id,branch_id,operator_actor_id,label,interval_seconds,event_types,anchor_seconds)
                    SELECT %s,p.world_id,p.branch_id,%s,%s,%s,%s::text[],
                      COALESCE((p.state->'tabletop.clock'->'singleton'->>'seconds')::bigint,0)
                    FROM sim.branch_projections p WHERE (p.world_id,p.branch_id)=(%s,%s)
                    RETURNING *""",
                    (
                        str(request.rule_id),
                        str(actor),
                        request.label,
                        request.interval_seconds,
                        sorted(request.event_types),
                        *scope,
                    ),
                )
                return CheckpointRule.model_validate(cursor.fetchone())

    def retire(
        self, world: uuid.UUID, branch: uuid.UUID, rule_id: uuid.UUID, actor: uuid.UUID
    ) -> None:
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.holds.authorize(cursor, world, actor, private=True)
                self.holds._require_branch(cursor, world, branch, lock=True)
                require_checkpoint_open(cursor, world, branch)
                cursor.execute(
                    "UPDATE sim.campaign_checkpoint_rules SET active=false "
                    "WHERE (world_id,branch_id,rule_id)=(%s,%s,%s) AND active",
                    (str(world), str(branch), str(rule_id)),
                )

    def _ready(self) -> tuple[ScheduledCheckpoint, ...]:
        now = time.monotonic()
        self._retry_after = {key: value for key, value in self._retry_after.items() if value > now}
        with transaction(actor_id=self.machine_actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT job.world_id,job.branch_id,job.request_id,rule.operator_actor_id,
                              rule.label,job.cause,job.source_event_id
                       FROM sim.campaign_checkpoint_dispatches job
                       JOIN sim.campaign_checkpoint_rules rule
                         ON (rule.world_id,rule.branch_id,rule.rule_id)=
                            (job.world_id,job.branch_id,job.rule_id)
                       JOIN sim.campaign_checkpoint_holds hold
                         ON (hold.world_id,hold.branch_id,hold.request_id)=
                            (job.world_id,job.branch_id,job.request_id)
                       WHERE hold.released_at IS NULL AND job.request_id<>ALL(%s::uuid[])
                         AND NOT EXISTS (
                           SELECT 1 FROM sim.events source JOIN sim.outbox work
                             ON work.event_id=source.event_id
                           WHERE (source.world_id,source.branch_id)=(job.world_id,job.branch_id)
                             AND source.seq_id<=hold.through_event_seq AND work.published_at IS NULL
                         )
                       ORDER BY job.created_at,job.request_id LIMIT 8""",
                    ([str(key) for key in self._retry_after],),
                )
                return tuple(ScheduledCheckpoint.model_validate(row) for row in cursor)

    def run_ready(self) -> int:
        finished = 0
        for job in self._ready():
            scope = (job.world_id, job.branch_id, job.request_id, job.operator_actor_id)
            try:
                self.archives.capture(*scope, job.label)
                self.holds.release(*scope)
            except (
                CheckpointHoldConflict,
                PermissionError,
                KeyError,
                psycopg2.errors.SerializationFailure,
            ):
                # The request remains held and discoverable for an operator or a later attempt.
                self._retry_after[job.request_id] = time.monotonic() + 10
            else:
                finished += 1
        return finished
