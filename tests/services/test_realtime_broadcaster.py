import pytest
import logging

pytestmark = pytest.mark.unit


class FakeSocketIO:
    def __init__(self):
        self.calls = []

    def emit(self, event, payload, room=None):
        self.calls.append({"event": event, "payload": payload, "room": room})


def _env(**overrides):
    from services.realtime.broadcaster import BroadcastEnvelope

    data = {
        "event_id": "evt-1",
        "campaign_id": "camp-1",
        "session_id": "sess-1",
        "event_type": "game_event",
        "payload": {"message": "test"},
    }
    data.update(overrides)
    return BroadcastEnvelope(**data)


def test_dm_only_event_goes_only_to_dm_room(monkeypatch):
    from services.realtime import broadcaster

    fake = FakeSocketIO()
    monkeypatch.setattr(
        broadcaster,
        "resolve_principal_audience",
        lambda **kwargs: (set(), "dm_only"),
    )

    deliveries = broadcaster.broadcast_game_event(
        _env(visibility="dm_only"),
        socketio=fake,
    )

    assert [c["room"] for c in fake.calls] == ["dm:camp-1"]
    assert deliveries[0]["scope"] == "dm"


def test_public_event_uses_public_campaign_room_and_dm(monkeypatch):
    from services.realtime import broadcaster

    fake = FakeSocketIO()
    monkeypatch.setattr(
        broadcaster,
        "resolve_principal_audience",
        lambda **kwargs: ({"player-1"}, "public"),
    )

    broadcaster.broadcast_game_event(_env(visibility="public"), socketio=fake)

    assert [c["room"] for c in fake.calls] == ["campaign:camp-1:public", "dm:camp-1"]
    assert "camp-1" not in [c["room"] for c in fake.calls]


def test_principal_scoped_event_goes_to_listed_principals_and_dm(monkeypatch):
    from services.realtime import broadcaster

    fake = FakeSocketIO()
    monkeypatch.setattr(
        broadcaster,
        "resolve_principal_audience",
        lambda **kwargs: ({"p2", "p1"}, "explicit_visible_to"),
    )

    broadcaster.broadcast_game_event(
        _env(visibility="principal_scoped", visible_to=["p1", "p2"]),
        socketio=fake,
    )

    assert [c["room"] for c in fake.calls] == [
        "principal:p1",
        "principal:p2",
        "dm:camp-1",
    ]
    assert fake.calls[0]["payload"]["delivery"]["reason"] == "explicit_visible_to"


def test_spatial_event_uses_resolved_witnesses_plus_dm(monkeypatch):
    from services.realtime import broadcaster

    fake = FakeSocketIO()
    captured = {}

    def fake_resolve(**kwargs):
        captured.update(kwargs)
        return {"pc-a"}, "spatial"

    monkeypatch.setattr(broadcaster, "resolve_principal_audience", fake_resolve)

    broadcaster.broadcast_game_event(
        _env(visibility="spatial", map_id="map-1", x=3, y=4),
        socketio=fake,
    )

    assert captured["map_id"] == "map-1"
    assert captured["x"] == 3
    assert captured["y"] == 4
    assert [c["room"] for c in fake.calls] == ["principal:pc-a", "dm:camp-1"]


def test_explicit_visible_to_does_not_widen_through_spatial(monkeypatch):
    from services.realtime import audience

    monkeypatch.setattr(audience, "dm_principals", lambda campaign_id: set())
    monkeypatch.setattr(
        audience, "spatial_principals", lambda **kwargs: {"pc-a", "pc-b"}
    )

    principals, reason = audience.resolve_principal_audience(
        campaign_id="camp-1",
        visibility="spatial",
        visible_to=["pc-a"],
        map_id="map-1",
        x=1,
        y=1,
    )

    assert principals == {"pc-a"}
    assert reason == "explicit_visible_to"


def test_spatial_audience_filters_dm_principals(monkeypatch):
    from services.realtime import audience

    monkeypatch.setattr(
        "services.domain.maps.decoherence.audience_for_event",
        lambda **kwargs: ["dm-1", "pc-a"],
    )
    monkeypatch.setattr(audience, "dm_principals", lambda campaign_id: {"dm-1"})

    assert audience.spatial_principals(
        campaign_id="11111111-1111-1111-1111-111111111111",
        map_id=None,
        x=None,
        y=None,
    ) == {"pc-a"}


def test_validate_socket_join_rejects_unknown_principal(monkeypatch):
    from services.realtime import audience

    monkeypatch.setattr(
        audience, "load_principal", lambda principal_id, campaign_id: None
    )

    with pytest.raises(PermissionError):
        audience.validate_socket_join(
            campaign_id="11111111-1111-1111-1111-111111111111",
            principal_id="22222222-2222-2222-2222-222222222222",
            session_id=None,
        )


def test_payload_for_uses_envelope_visibility_as_canonical():
    from services.realtime.broadcaster import _payload_for

    payload = _payload_for(
        _env(visibility="dm_only", payload={"visibility": "public"}),
        scope="dm",
        reason="dm_receives_all",
        room="dm:camp-1",
    )

    assert payload["visibility"] == "dm_only"


def test_payload_for_logs_conflicting_payload_visibility(caplog):
    from services.realtime.broadcaster import _payload_for

    with caplog.at_level(logging.WARNING, logger="services.realtime.broadcaster"):
        _payload_for(
            _env(visibility="dm_only", payload={"visibility": "public"}),
            scope="dm",
            reason="dm_receives_all",
            room="dm:camp-1",
        )

    assert "overridden by canonical envelope visibility" in caplog.text
