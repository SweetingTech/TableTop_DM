import pytest

from services.api.application import _parse_socketio_cors_allowed_origins

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw_origins", [None, "", "   "])
def test_socketio_cors_defaults_to_same_origin(raw_origins):
    assert _parse_socketio_cors_allowed_origins(raw_origins) is None


def test_socketio_cors_parses_and_trims_allowlist():
    assert _parse_socketio_cors_allowed_origins(
        "http://localhost:8000, https://table.example , ,"
    ) == ["http://localhost:8000", "https://table.example"]


def test_socketio_cors_wildcard_requires_explicit_configuration():
    assert _parse_socketio_cors_allowed_origins("*") == "*"
