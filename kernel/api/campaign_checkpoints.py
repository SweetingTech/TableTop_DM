from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from flask import Flask, jsonify, request
from pydantic import BaseModel, ConfigDict, StringConstraints

from kernel.checkpoint_holds import CheckpointHoldConflict, CheckpointHolds, CheckpointHoldStatus
from kernel.errors import BranchCheckpointHeld
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints


class CheckpointHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID


class CheckpointCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


def register_checkpoint_holds(
    app: Flask,
    holds: CheckpointHolds,
    current_actor: Callable[[], uuid.UUID],
    require_world_access: Callable[[uuid.UUID], None],
) -> None:
    root = "/api/v2/worlds/<uuid:world_id>/branches/<uuid:branch_id>/checkpoint-holds"

    def status_response(status: CheckpointHoldStatus | None):
        response = jsonify(status.model_dump(mode="json") if status is not None else {"hold": None})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(BranchCheckpointHeld)
    def branch_held(error: BranchCheckpointHeld):
        return jsonify({"error": "branch_checkpoint_held", "details": str(error)}), 409

    @app.errorhandler(CheckpointHoldConflict)
    def hold_conflict(error: CheckpointHoldConflict):
        return jsonify({"error": "checkpoint_hold_conflict", "details": str(error)}), 409

    @app.post(root)
    def begin_checkpoint_hold(world_id: uuid.UUID, branch_id: uuid.UUID):
        require_world_access(world_id)
        body = CheckpointHoldRequest.model_validate(request.get_json(silent=True) or {})
        status = holds.begin(world_id, branch_id, body.request_id, current_actor())
        return status_response(status)

    @app.get(root)
    def active_checkpoint_hold(world_id: uuid.UUID, branch_id: uuid.UUID):
        require_world_access(world_id)
        status = holds.active(world_id, branch_id, current_actor())
        return status_response(status)

    @app.get(root + "/<uuid:request_id>")
    def read_checkpoint_hold(world_id: uuid.UUID, branch_id: uuid.UUID, request_id: uuid.UUID):
        require_world_access(world_id)
        status = holds.read(world_id, branch_id, request_id, current_actor())
        return status_response(status)

    @app.post(root + "/<uuid:request_id>/release")
    def release_checkpoint_hold(world_id: uuid.UUID, branch_id: uuid.UUID, request_id: uuid.UUID):
        require_world_access(world_id)
        status = holds.release(world_id, branch_id, request_id, current_actor())
        return status_response(status)


def register_checkpoint_capture(
    app: Flask,
    archives: PostgresCampaignCheckpoints,
    current_actor: Callable[[], uuid.UUID],
    require_world_access: Callable[[uuid.UUID], None],
) -> None:
    scope = "/api/v2/worlds/<uuid:world_id>/branches/<uuid:branch_id>"

    @app.post(scope + "/checkpoint-holds/<uuid:request_id>/capture")
    def capture_checkpoint(world_id: uuid.UUID, branch_id: uuid.UUID, request_id: uuid.UUID):
        require_world_access(world_id)
        body = CheckpointCaptureRequest.model_validate(request.get_json(silent=True) or {})
        receipt = archives.capture(world_id, branch_id, request_id, current_actor(), body.label)
        response = jsonify(receipt.model_dump(mode="json"))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get(scope + "/campaign-checkpoints/<uuid:checkpoint_id>")
    def read_campaign_checkpoint(
        world_id: uuid.UUID, branch_id: uuid.UUID, checkpoint_id: uuid.UUID
    ):
        require_world_access(world_id)
        receipt, _ = archives.load(world_id, branch_id, checkpoint_id, current_actor())
        response = jsonify(receipt.model_dump(mode="json"))
        response.headers["Cache-Control"] = "no-store"
        return response
