import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = pytest.mark.contracts

SCHEMA_PATH = Path("docs/schemas/event_envelope.schema.json")


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_event_envelope_accepts_valid_payload() -> None:
    schema = _load_schema()
    valid_envelope = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_version": 1,
        "contract_version": 1,
        "idempotency_key": "enc-555:playerA:turn1:attack",
        "type": "STATE_DELTA",
        "occurred_at": "2026-01-18T20:14:36.210Z",
        "campaign_id": "11111111-1111-1111-1111-111111111111",
        "session_id": "66666666-6666-6666-6666-666666666661",
        "encounter_id": None,
        "sender": {
            "principal_id": "22222222-2222-2222-2222-222222222222",
            "entity_id": None,
            "role": "PLAYER",
        },
        "payload": {"changes": [{"field": "hp_current", "from": 28, "to": 24}]},
        "visibility": {
            "visible_to": [
                "22222222-2222-2222-2222-222222222221",
                "22222222-2222-2222-2222-222222222222",
            ],
            "scope": "PARTY_ONLY",
        },
        "trace": {
            "parent_event_id": None,
            "causation_id": None,
            "correlation_id": None,
            "domain_tags": ["combat.damage"],
            "schema_uri": "ttdm.event.envelope.v1",
        },
        "integrity": {
            "source_service": "orchestrator",
            "sequence_hint": 42,
            "hash": "sha256:abc123",
        },
    }

    jsonschema.validate(instance=valid_envelope, schema=schema)


def test_event_envelope_rejects_empty_visibility() -> None:
    schema = _load_schema()
    invalid_envelope = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_version": 1,
        "contract_version": 1,
        "idempotency_key": "enc-555:playerA:turn1:attack",
        "type": "STATE_DELTA",
        "occurred_at": "2026-01-18T20:14:36.210Z",
        "campaign_id": "11111111-1111-1111-1111-111111111111",
        "session_id": "66666666-6666-6666-6666-666666666661",
        "sender": {
            "principal_id": "22222222-2222-2222-2222-222222222222",
            "entity_id": None,
            "role": "PLAYER",
        },
        "payload": {},
        "visibility": {"visible_to": [], "scope": "PARTY_ONLY"},
        "trace": {
            "parent_event_id": None,
            "causation_id": None,
            "correlation_id": None,
            "domain_tags": ["combat.damage"],
            "schema_uri": "ttdm.event.envelope.v1",
        },
        "integrity": {
            "source_service": "orchestrator",
            "sequence_hint": 42,
            "hash": "sha256:abc123",
        },
    }

    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(invalid_envelope))

    assert any(
        list(error.path) == ["visibility", "visible_to"]
        and error.validator == "minItems"
        for error in errors
    )
