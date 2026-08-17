from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from experiments.telemetry import (
    PostgresTelemetryRepository,
    TelemetryEvent,
    TelemetryRecorder,
    TelemetrySettingsStore,
)

pytestmark = pytest.mark.integration


def _seed_telemetry_world(integration_stack) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    world_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    participant_id = uuid.uuid4()
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sim.worlds(id, slug, name) VALUES (%s, %s, 'Telemetry Test')",
                (str(world_id), f"telemetry-{world_id.hex[:10]}"),
            )
            cursor.execute(
                """
                INSERT INTO sim.actors(id, actor_kind, display_name)
                VALUES (%s, 'HUMAN', 'Operator'), (%s, 'HUMAN', 'Participant')
                """,
                (str(operator_id), str(participant_id)),
            )
            cursor.execute(
                """
                INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s, %s, 'metric.evaluate')
                """,
                (str(world_id), str(operator_id)),
            )
    return world_id, operator_id, participant_id


def _event(
    *, world_id: uuid.UUID, actor_id: uuid.UUID, captured_at: datetime, label: str
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid.uuid4(),
        world_id=world_id,
        actor_id=actor_id,
        event_type="integration.telemetry",
        payload={"label": label},
        consent_version="integration-v1",
        captured_at=captured_at,
    )


def test_durable_telemetry_honors_selective_delete_and_retention(
    integration_stack,
) -> None:
    world_id, operator_id, participant_id = _seed_telemetry_world(integration_stack)
    settings = TelemetrySettingsStore(integration_stack.database_url)
    assert settings.configure(enabled=True, retention_days=30).human_telemetry_enabled

    repository = PostgresTelemetryRepository(integration_stack.database_url, operator_id)
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    participant_old = _event(
        world_id=world_id,
        actor_id=participant_id,
        captured_at=now - timedelta(days=45),
        label="participant-old",
    )
    operator_old = _event(
        world_id=world_id,
        actor_id=operator_id,
        captured_at=now - timedelta(days=31),
        label="operator-old",
    )
    participant_recent = _event(
        world_id=world_id,
        actor_id=participant_id,
        captured_at=now - timedelta(days=2),
        label="participant-recent",
    )
    for event in (participant_old, operator_old, participant_recent):
        repository.add(event)

    assert [event.payload["label"] for event in repository.list()] == [
        "participant-old",
        "operator-old",
        "participant-recent",
    ]
    assert (
        repository.delete(
            world_id=world_id,
            actor_id=participant_id,
            before=now - timedelta(days=30),
        )
        == 1
    )

    recorder = TelemetryRecorder(settings, repository, clock=lambda: now)
    assert recorder.purge_expired(now=now) == 1
    remaining = recorder.events()
    assert [event.event_id for event in remaining] == [participant_recent.event_id]

    settings.set_enabled(False)
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        repository.add(
            _event(
                world_id=world_id,
                actor_id=participant_id,
                captured_at=now,
                label="disabled",
            )
        )
