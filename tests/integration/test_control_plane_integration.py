from pathlib import Path

import pytest

from app import app
from shared.db.connection import execute_one

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _seed_campaign_id():
    row = execute_one("SELECT id FROM state.campaigns ORDER BY created_at DESC LIMIT 1")
    return str(row["id"])


def test_control_plane_crud_and_rag(integration_stack):
    fixture = Path(__file__).parent / "fixtures" / "rag_doc.txt"

    with app.test_client() as client:
        campaign = client.post(
            "/api/campaigns",
            json={"name": "CP IT", "slug": "cp-it", "status": "ACTIVE", "mode": "EXPLORATION"},
        )
        assert campaign.status_code == 201
        campaign_id = campaign.get_json()["id"]

        updated = client.put(f"/api/campaigns/{campaign_id}", json={"mode": "SOCIAL"})
        assert updated.status_code == 200
        assert updated.get_json()["mode"] == "SOCIAL"

        session = client.post(f"/api/campaigns/{campaign_id}/sessions")
        assert session.status_code == 201
        session_id = session.get_json()["id"]
        assert client.post(f"/api/sessions/{session_id}/pause").status_code == 200
        assert client.post(f"/api/sessions/{session_id}/resume").status_code == 200
        assert client.post(f"/api/sessions/{session_id}/end").status_code == 200

        ent = client.post(
            f"/api/campaigns/{campaign_id}/entities",
            json={"name": "Import Hero", "entity_type": "PC", "public_sheet": {"class": "Rogue"}},
        )
        assert ent.status_code == 201
        entity_id = ent.get_json()["id"]
        control = client.post(f"/api/entities/{entity_id}/control", json={"controlled_by": "AI"})
        assert control.status_code == 200
        assert control.get_json()["controlled_by"] == "AI"

        ai_cfg = client.put(
            f"/api/campaigns/{campaign_id}/ai_config",
            json={
                "llm_provider": "ollama",
                "llm_base_url": "http://localhost:11434/v1/",
                "dm_model": "llama3",
                "npc_model": "llama3",
                "embedding_model": "embeddinggemma",
            },
        )
        assert ai_cfg.status_code == 200
        assert ai_cfg.get_json()["llm_provider"] == "ollama"

        with fixture.open("rb") as fh:
            upload = client.post(
                f"/api/campaigns/{campaign_id}/rag/upload",
                data={"file": (fh, "rag_doc.txt")},
                content_type="multipart/form-data",
            )
        assert upload.status_code == 201
        assert upload.get_json()["status"] in {"READY", "FAILED"}

        docs = client.get(f"/api/campaigns/{campaign_id}/rag/documents")
        assert docs.status_code == 200
        assert len(docs.get_json()) >= 1

        query = client.post(
            f"/api/campaigns/{campaign_id}/rag/query",
            json={"query": "silver key", "top_k": 3},
        )
        assert query.status_code == 200
        assert "results" in query.get_json()

        assert client.delete(f"/api/campaigns/{campaign_id}").status_code == 200
