import pytest

from app import app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def test_readyz_verbose_reports_dependency_checks(integration_stack):
    with app.test_client() as client:
        response = client.get("/readyz?verbose=1")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ready"] is True
    assert {"postgres", "redis", "qdrant", "migrations"} <= set(body["checks"])
    for name in ("postgres", "redis", "qdrant", "migrations"):
        assert body["checks"][name]["ok"] is True
        assert "latency_ms" in body["checks"][name]


def test_readyz_verbose_identifies_failed_dependency(integration_stack, monkeypatch):
    monkeypatch.setenv("QDRANT_HTTP_PORT", "1")

    with app.test_client() as client:
        response = client.get("/readyz?verbose=1")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ready"] is False
    assert body["checks"]["qdrant"]["ok"] is False
    assert "error" in body["checks"]["qdrant"]


def test_dashboard_route_returns_200(integration_stack):
    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert b"TABLETOP DM" in response.data
