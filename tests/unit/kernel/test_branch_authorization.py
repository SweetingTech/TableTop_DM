from __future__ import annotations

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def test_trial_branch_endpoint_requires_world_scoped_run_branch_capability(
    tmp_path,
) -> None:
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]

    with app.test_client() as client:
        snapshot = client.post(f"/api/v2/worlds/{ids['world_id']}/snapshots").get_json()
        observer = client.post(
            "/api/v2/actors",
            json={
                "display_name": "Branch observer",
                "kind": "HUMAN",
                "world_id": str(ids["world_id"]),
                "roles": ["OBSERVER"],
                "capabilities": ["world.read"],
            },
        ).get_json()
        before = len(app.extensions["simulation"].states.all())
        denied = client.post(
            f"/api/v2/snapshots/{snapshot['snapshot_id']}/branches",
            headers={"X-TTDM-Actor-ID": observer["actor_id"]},
            json={"seed": 401},
        )
        after_denied = len(app.extensions["simulation"].states.all())
        allowed = client.post(
            f"/api/v2/snapshots/{snapshot['snapshot_id']}/branches",
            json={"seed": 402},
        )

    assert denied.status_code == 403
    assert denied.get_json()["error"] == "permission_denied"
    assert after_denied == before
    assert allowed.status_code == 201
    assert allowed.get_json()["branch_kind"] == "TRIAL"
