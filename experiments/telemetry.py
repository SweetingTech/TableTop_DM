from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import psycopg2.extras
from pydantic import BaseModel, ConfigDict, Field

from kernel.database import execute_one, transaction


class TelemetrySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    human_telemetry_enabled: bool = False
    local_only: bool = True
    retention_days: int = Field(default=30, ge=1, le=3650)


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    consent_version: str
    captured_at: datetime
    world_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None


class TelemetryRepository(Protocol):
    def add(self, event: TelemetryEvent) -> None: ...

    def list(self) -> tuple[TelemetryEvent, ...]: ...

    def delete(
        self,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        before: datetime | None = None,
    ) -> int: ...


class InMemoryTelemetryRepository:
    def __init__(self) -> None:
        self._events: dict[uuid.UUID, TelemetryEvent] = {}
        self._lock = threading.RLock()

    def add(self, event: TelemetryEvent) -> None:
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None and existing != event:
                raise ValueError("Telemetry event ID collision")
            self._events[event.event_id] = event.model_copy(deep=True)

    def list(self) -> tuple[TelemetryEvent, ...]:
        with self._lock:
            return tuple(
                event.model_copy(deep=True)
                for event in sorted(
                    self._events.values(),
                    key=lambda item: (item.captured_at, str(item.event_id)),
                )
            )

    def delete(
        self,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        before: datetime | None = None,
    ) -> int:
        with self._lock:
            selected = [
                event_id
                for event_id, event in self._events.items()
                if (world_id is None or event.world_id == world_id)
                and (actor_id is None or event.actor_id == actor_id)
                and (before is None or event.captured_at < before)
            ]
            for event_id in selected:
                del self._events[event_id]
            return len(selected)


class PostgresTelemetryRepository:
    """RLS-aware durable capture repository scoped to an operator actor."""

    def __init__(self, dsn: str, actor_id: uuid.UUID) -> None:
        self.dsn = dsn
        self.actor_id = actor_id

    def add(self, event: TelemetryEvent) -> None:
        if event.world_id is None or event.actor_id is None:
            raise ValueError("durable telemetry requires world_id and actor_id")
        with transaction(actor_id=event.actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO experiments.telemetry_captures (
                      id, world_id, actor_id, event_type, payload,
                      consent_version, captured_at
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(event.event_id),
                        str(event.world_id),
                        str(event.actor_id),
                        event.event_type,
                        json.dumps(event.payload, default=str),
                        event.consent_version,
                        event.captured_at,
                    ),
                )

    def list(self) -> tuple[TelemetryEvent, ...]:
        with transaction(actor_id=self.actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, world_id, actor_id, event_type, payload,
                           consent_version, captured_at
                    FROM experiments.telemetry_captures
                    ORDER BY captured_at, id
                    """
                )
                rows = cursor.fetchall()
        return tuple(
            TelemetryEvent(
                event_id=row["id"],
                world_id=row["world_id"],
                actor_id=row["actor_id"],
                event_type=row["event_type"],
                payload=row["payload"],
                consent_version=row["consent_version"],
                captured_at=row["captured_at"],
            )
            for row in rows
        )

    def delete(
        self,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        before: datetime | None = None,
    ) -> int:
        clauses: list[str] = []
        parameters: list[Any] = []
        if world_id is not None:
            clauses.append("world_id = %s")
            parameters.append(str(world_id))
        if actor_id is not None:
            clauses.append("actor_id = %s")
            parameters.append(str(actor_id))
        if before is not None:
            clauses.append("captured_at < %s")
            parameters.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with transaction(actor_id=self.actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM experiments.telemetry_captures" + where,
                    parameters,
                )
                return cursor.rowcount


class TelemetrySettingsStore:
    """Local-first settings with an optional durable PostgreSQL adapter."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn
        self._local = TelemetrySettings()
        self._lock = threading.RLock()

    def get(self) -> TelemetrySettings:
        if self.dsn is None:
            with self._lock:
                return self._local
        row = execute_one(
            """
            SELECT human_telemetry_enabled, local_only, retention_days
            FROM experiments.telemetry_settings WHERE singleton = true
            """,
            dsn=self.dsn,
        )
        return TelemetrySettings.model_validate(row or {})

    def set_enabled(self, enabled: bool) -> TelemetrySettings:
        return self.configure(enabled=enabled)

    def configure(
        self,
        *,
        enabled: bool | None = None,
        retention_days: int | None = None,
    ) -> TelemetrySettings:
        current = self.get()
        updated = TelemetrySettings(
            human_telemetry_enabled=(
                current.human_telemetry_enabled if enabled is None else enabled
            ),
            retention_days=(current.retention_days if retention_days is None else retention_days),
            local_only=True,
        )
        if self.dsn is None:
            with self._lock:
                self._local = updated
                return self._local
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO experiments.telemetry_settings (
                      singleton, human_telemetry_enabled, local_only,
                      retention_days, enabled_at, updated_at
                    ) VALUES (true, %s, true, %s,
                              CASE WHEN %s THEN now() ELSE NULL END, now())
                    ON CONFLICT (singleton) DO UPDATE SET
                      human_telemetry_enabled = EXCLUDED.human_telemetry_enabled,
                      local_only = true,
                      retention_days = EXCLUDED.retention_days,
                      enabled_at = EXCLUDED.enabled_at,
                      updated_at = now()
                    RETURNING human_telemetry_enabled, local_only, retention_days
                    """,
                    (
                        updated.human_telemetry_enabled,
                        updated.retention_days,
                        updated.human_telemetry_enabled,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("telemetry settings update returned no row")
        return TelemetrySettings(
            human_telemetry_enabled=bool(row[0]),
            local_only=bool(row[1]),
            retention_days=int(row[2]),
        )


class TelemetryRecorder:
    SENSITIVE_KEYS = frozenset(
        {"token", "password", "secret", "api_key", "authorization", "cookie"}
    )

    def __init__(
        self,
        settings: TelemetrySettingsStore,
        repository: TelemetryRepository | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or InMemoryTelemetryRepository()
        self.clock = clock or (lambda: datetime.now(UTC))

    def capture(
        self,
        event_type: str,
        payload: dict[str, Any],
        consent_version: str,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> TelemetryEvent:
        if not self.settings.get().human_telemetry_enabled:
            raise PermissionError("human telemetry is disabled")
        event_type = event_type.strip()
        consent_version = consent_version.strip()
        if not event_type or not consent_version:
            raise ValueError("event_type and consent_version are required")
        redacted = self._redact(copy.deepcopy(payload))
        captured_at = self.clock()
        if captured_at.tzinfo is None:
            raise ValueError("telemetry timestamps must be timezone-aware")
        event = TelemetryEvent(
            event_id=uuid.uuid4(),
            event_type=event_type,
            payload=redacted,
            consent_version=consent_version,
            captured_at=captured_at,
            world_id=world_id,
            actor_id=actor_id,
        )
        self.repository.add(event)
        return event

    def events(self) -> tuple[TelemetryEvent, ...]:
        return self.repository.list()

    def export(
        self,
        destination: Path,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Path:
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        events = tuple(
            event
            for event in self.repository.list()
            if (world_id is None or event.world_id == world_id)
            and (actor_id is None or event.actor_id == actor_id)
        )
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            "\n".join(event.model_dump_json() for event in events),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return destination

    def delete(
        self,
        *,
        world_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        before: datetime | None = None,
    ) -> int:
        return self.repository.delete(
            world_id=world_id,
            actor_id=actor_id,
            before=before,
        )

    def delete_all(self) -> int:
        return self.repository.delete()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        settings = self.settings.get()
        threshold = (now or self.clock()) - timedelta(days=settings.retention_days)
        return self.repository.delete(before=threshold)

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if str(key).casefold() in self.SENSITIVE_KEYS
                    else self._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        return value
