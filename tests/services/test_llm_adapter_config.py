import uuid
import pytest
from unittest.mock import patch
from services.llm.adapter import get_campaign_ai_config

@pytest.mark.unit
def test_get_campaign_ai_config_none_id():
    """Verify {} is returned when campaign_id is None."""
    assert get_campaign_ai_config(None) == {}

@pytest.mark.unit
def test_get_campaign_ai_config_success():
    """Verify the correct row is returned when the database query succeeds."""
    campaign_id = uuid.uuid4()
    mock_row = {"llm_provider": "openai", "dm_model": "gpt-4o"}

    with patch("shared.db.connection.execute_one") as mock_execute:
        mock_execute.return_value = mock_row
        result = get_campaign_ai_config(campaign_id)

        assert result == mock_row
        mock_execute.assert_called_once_with(
            "SELECT * FROM state.campaign_settings WHERE campaign_id=%s", (str(campaign_id),)
        )

@pytest.mark.unit
def test_get_campaign_ai_config_not_found():
    """Verify {} is returned when the database query returns None."""
    campaign_id = uuid.uuid4()

    with patch("shared.db.connection.execute_one") as mock_execute:
        mock_execute.return_value = None
        result = get_campaign_ai_config(campaign_id)

        assert result == {}

@pytest.mark.unit
def test_get_campaign_ai_config_exception(caplog):
    """Verify {} is returned and exception is handled when the database query raises an error."""
    campaign_id = uuid.uuid4()

    with patch("shared.db.connection.execute_one") as mock_execute:
        mock_execute.side_effect = Exception("DB Error")
        result = get_campaign_ai_config(campaign_id)

        assert result == {}
        assert "Failed to retrieve campaign AI config" in caplog.text
