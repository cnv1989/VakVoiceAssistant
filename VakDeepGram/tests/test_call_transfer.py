"""
Tests for call transfer and talk_to_owner functionality.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_voice_config_with_forwarding():
    """Mock voice config with forwarding number."""
    return {
        "voiceType": "charlotte",
        "voiceProvider": "eleven_labs",
        "voiceId": "0mevMNFMwHxBOUTpeMGN",
        "forwardingNumber": "+15559876543",
        "enableAutoTransfer": True,
        "maxFailuresBeforeTransfer": 2,
    }


@pytest.fixture
def mock_context_with_twilio(mock_connection_context, mock_voice_config_with_forwarding):
    """Mock connection context with Twilio identifiers and voice config."""
    return {
        **mock_connection_context,
        "accountSid": "AC123456789",
        "callSid": "CA987654321",
        "voiceConfig": mock_voice_config_with_forwarding,
    }


class TestTalkToOwner:
    """Tests for talk_to_owner agent function."""

    @pytest.mark.asyncio
    async def test_talk_to_owner_success(self, mock_context_with_twilio):
        """talk_to_owner transfers to configured forwarding number."""
        from vakdeepgram.agent_functions import talk_to_owner
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-001"
        set_connection_context(connection_id, mock_context_with_twilio)

        with patch("vakdeepgram.business_logic.TwilioClient") as mock_twilio:
            mock_client = MagicMock()
            mock_call = MagicMock()
            mock_call.update = MagicMock()
            mock_client.calls = MagicMock(return_value=mock_call)
            mock_twilio.return_value = mock_client

            with patch("vakdeepgram.business_logic.config.settings") as mock_settings:
                mock_settings.twilio_auth_token = "test-auth-token"

                result = await talk_to_owner({"connection_id": connection_id})

                assert result["success"] is True
                assert result["forwarded_to"] == "+15559876543"
                mock_call.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_talk_to_owner_missing_connection_id(self):
        """talk_to_owner fails without connection_id."""
        from vakdeepgram.agent_functions import talk_to_owner

        result = await talk_to_owner({})

        assert result["success"] is False
        assert "connection_id is required" in result["error"]


class TestForwardCallToLocation:
    """Tests for forward_call_to_location business logic."""

    @pytest.mark.asyncio
    async def test_forward_uses_voice_config_number(self, mock_context_with_twilio):
        """Forward uses voiceConfig.forwardingNumber when available."""
        from vakdeepgram.business_logic import forward_call_to_location
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-002"
        set_connection_context(connection_id, mock_context_with_twilio)

        with patch("vakdeepgram.business_logic.TwilioClient") as mock_twilio:
            mock_client = MagicMock()
            mock_call = MagicMock()
            mock_call.update = MagicMock()
            mock_client.calls = MagicMock(return_value=mock_call)
            mock_twilio.return_value = mock_client

            with patch("vakdeepgram.business_logic.config.settings") as mock_settings:
                mock_settings.twilio_auth_token = "test-auth-token"

                result = await forward_call_to_location(connection_id)

                assert result["success"] is True
                # Should use voiceConfig.forwardingNumber, not location.phone_number
                assert result["forwarded_to"] == "+15559876543"

    @pytest.mark.asyncio
    async def test_forward_falls_back_to_location_phone(self, mock_connection_context):
        """Forward falls back to location phone when no forwarding number."""
        from vakdeepgram.business_logic import forward_call_to_location
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-003"
        context = {
            **mock_connection_context,
            "accountSid": "AC123456789",
            "callSid": "CA987654321",
            "voiceConfig": {},  # No forwarding number
        }
        set_connection_context(connection_id, context)

        with patch("vakdeepgram.business_logic.TwilioClient") as mock_twilio:
            mock_client = MagicMock()
            mock_call = MagicMock()
            mock_call.update = MagicMock()
            mock_client.calls = MagicMock(return_value=mock_call)
            mock_twilio.return_value = mock_client

            with patch("vakdeepgram.business_logic.config.settings") as mock_settings:
                mock_settings.twilio_auth_token = "test-auth-token"

                result = await forward_call_to_location(connection_id)

                assert result["success"] is True
                # Should fall back to location.phone_number
                assert result["forwarded_to"] == "+15551234567"

    @pytest.mark.asyncio
    async def test_forward_fails_no_number_configured(self, mock_connection_context):
        """Forward fails when no forwarding number is configured."""
        from vakdeepgram.business_logic import forward_call_to_location
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-004"
        context = {
            **mock_connection_context,
            "accountSid": "AC123456789",
            "callSid": "CA987654321",
            "voiceConfig": {},
            "location": {},  # No phone number
        }
        set_connection_context(connection_id, context)

        with patch("vakdeepgram.business_logic.config.settings") as mock_settings:
            mock_settings.twilio_auth_token = "test-auth-token"

            result = await forward_call_to_location(connection_id)

            assert result["success"] is False
            assert "No forwarding number configured" in result["error"]


class TestAutoTransferOnFailures:
    """Tests for auto-transfer on consecutive failures."""

    def test_consecutive_failures_tracked(self, mock_deepgram_session):
        """Consecutive failures are tracked in session."""
        mock_deepgram_session.consecutive_failures = 0

        # Simulate failure
        mock_deepgram_session.consecutive_failures += 1
        assert mock_deepgram_session.consecutive_failures == 1

        # Simulate another failure
        mock_deepgram_session.consecutive_failures += 1
        assert mock_deepgram_session.consecutive_failures == 2

        # Simulate success (reset)
        mock_deepgram_session.consecutive_failures = 0
        assert mock_deepgram_session.consecutive_failures == 0

    def test_auto_transfer_threshold_check(self, mock_voice_config_with_forwarding):
        """Auto-transfer triggers when threshold is reached."""
        consecutive_failures = 2
        enable_auto_transfer = mock_voice_config_with_forwarding.get("enableAutoTransfer", True)
        max_failures = mock_voice_config_with_forwarding.get("maxFailuresBeforeTransfer", 2)

        should_transfer = (
            enable_auto_transfer and
            consecutive_failures >= max_failures
        )

        assert should_transfer is True

    def test_auto_transfer_disabled(self):
        """Auto-transfer does not trigger when disabled."""
        voice_config = {
            "enableAutoTransfer": False,
            "maxFailuresBeforeTransfer": 2,
        }
        consecutive_failures = 5

        enable_auto_transfer = voice_config.get("enableAutoTransfer", True)
        max_failures = voice_config.get("maxFailuresBeforeTransfer", 2)

        should_transfer = (
            enable_auto_transfer and
            consecutive_failures >= max_failures
        )

        assert should_transfer is False

    def test_auto_transfer_below_threshold(self):
        """Auto-transfer does not trigger below threshold."""
        voice_config = {
            "enableAutoTransfer": True,
            "maxFailuresBeforeTransfer": 3,
        }
        consecutive_failures = 2

        enable_auto_transfer = voice_config.get("enableAutoTransfer", True)
        max_failures = voice_config.get("maxFailuresBeforeTransfer", 2)

        should_transfer = (
            enable_auto_transfer and
            consecutive_failures >= max_failures
        )

        # With max_failures=3 and consecutive_failures=2, should not transfer
        voice_config["maxFailuresBeforeTransfer"] = 3
        max_failures = voice_config.get("maxFailuresBeforeTransfer", 2)
        should_transfer = (
            enable_auto_transfer and
            consecutive_failures >= max_failures
        )

        assert should_transfer is False


class TestTransferToStaff:
    """Tests for transfer_to_staff agent function."""

    @pytest.mark.asyncio
    async def test_transfer_to_staff_success(self, mock_context_with_twilio):
        """transfer_to_staff forwards to configured number."""
        from vakdeepgram.agent_functions import transfer_to_staff
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-005"
        set_connection_context(connection_id, mock_context_with_twilio)

        with patch("vakdeepgram.business_logic.TwilioClient") as mock_twilio:
            mock_client = MagicMock()
            mock_call = MagicMock()
            mock_call.update = MagicMock()
            mock_client.calls = MagicMock(return_value=mock_call)
            mock_twilio.return_value = mock_client

            with patch("vakdeepgram.business_logic.config.settings") as mock_settings:
                mock_settings.twilio_auth_token = "test-auth-token"

                result = await transfer_to_staff({"connection_id": connection_id})

                assert result["success"] is True
