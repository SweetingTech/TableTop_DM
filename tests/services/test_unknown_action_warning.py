import uuid

import pytest

from services.orchestrator.pipeline import OrchestratorPipeline, ValidationError
from shared.auth.principal import PrincipalContext
from shared.schemas.contracts import InterventionProposal
from shared.schemas.enums import EventType, PrincipalType

pytestmark = pytest.mark.unit


CAMPAIGN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = uuid.UUID("66666666-6666-6666-6666-666666666661")
PLAYER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLAYER_ENTITY_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")
GM_ID = uuid.UUID("22222222-2222-2222-2222-222222222221")


def test_unknown_action_raises_and_emits_system_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = OrchestratorPipeline()
    captured = {}

    def fake_execute_query(_query: str, _params: tuple[str, ...]):
        return [{"principal_id": GM_ID}]

    def fake_append(event):
        captured["event"] = event

    monkeypatch.setattr("shared.db.connection.execute_query", fake_execute_query)
    monkeypatch.setattr(pipeline.ledger, "append_event", fake_append)

    principal = PrincipalContext(
        principal_id=PLAYER_ID,
        principal_type=PrincipalType.HUMAN,
        display_name="PlayerA",
        campaign_id=CAMPAIGN_ID,
        controlled_entity_ids=[PLAYER_ENTITY_ID],
    )
    proposal = InterventionProposal(
        action_type="DO_A_FLIP",
        params={"entity_id": str(PLAYER_ENTITY_ID)},
        proposer_principal_id=PLAYER_ID,
        campaign_id=CAMPAIGN_ID,
        session_id=SESSION_ID,
    )

    with pytest.raises(ValidationError, match="Unknown action_type: DO_A_FLIP"):
        pipeline.process_proposal(proposal, principal, SESSION_ID)

    warning = captured["event"]
    assert warning.type == EventType.SYSTEM_WARNING
    assert warning.payload["proposal"]["action_type"] == "DO_A_FLIP"
