from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from cognition.character_decisions import CharacterProposalReceipt, InMemoryCharacterProposals
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_receipt_rejects_mixed_lineage_and_repository_does_not_cache_failure(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, _, _, path, run, _ = setup_bound_character(app)
    raw = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "receipt"}
    ).get_json()
    receipt = CharacterProposalReceipt.model_validate(raw)
    for change in [
        {"actor_id": str(uuid.uuid4())},
        {"seed": receipt.seed + 1},
        {"decision_id": str(uuid.uuid4())},
        {"scope": {**raw["scope"], "entity_id": str(uuid.uuid4())}},
    ]:
        with pytest.raises(ValidationError, match="lineage"):
            CharacterProposalReceipt.model_validate({**raw, **change})
    repository = InMemoryCharacterProposals()
    with pytest.raises(ValueError, match="differs"):
        repository.get_or_create(
            receipt.scope,
            receipt.actor_id,
            "receipt",
            lambda: receipt.model_copy(update={"idempotency_key": "wrong"}),
        )
    assert (
        repository.get_or_create(receipt.scope, receipt.actor_id, "receipt", lambda: receipt)
        == receipt
    )
    assert (
        repository.get_or_create(
            receipt.scope,
            receipt.actor_id,
            "receipt",
            lambda: pytest.fail("retry regenerated a decision"),
        )
        == receipt
    )
