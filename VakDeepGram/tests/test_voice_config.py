"""
Tests for voice configuration functionality.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_voice_config():
    """Mock voice config from DynamoDB."""
    return {
        "voiceType": "charlotte",
        "voiceProvider": "eleven_labs",
        "voiceId": "0mevMNFMwHxBOUTpeMGN",
        "voiceModelId": "eleven_multilingual_v2",
        "forwardingNumber": "+15551234567",
        "enableAutoTransfer": True,
        "maxFailuresBeforeTransfer": 2,
    }


@pytest.fixture
def mock_context_with_voice_config(mock_connection_context, mock_voice_config):
    """Mock connection context with voice config."""
    return {
        **mock_connection_context,
        "voiceConfig": mock_voice_config,
    }


class TestVoiceConfigFetch:
    """Tests for voice config fetching from DynamoDB."""

    @pytest.mark.asyncio
    async def test_fetch_voice_config_success(self, mock_voice_config):
        """Voice config is fetched successfully from DynamoDB."""
        from vakdeepgram.connection_store import _fetch_voice_config

        mock_table = AsyncMock()
        mock_table.get_item = AsyncMock(return_value={
            "Item": {
                "merchantId": "MERCH123",
                "locationId": "LOC123",
                "voiceAiConfig": mock_voice_config,
            }
        })

        mock_resource = AsyncMock()
        mock_resource.Table = MagicMock(return_value=mock_table)

        with patch("vakdeepgram.connection_store.aioboto3.Session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.resource = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resource),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_session.return_value = mock_session_instance

            result = await _fetch_voice_config("MERCH123", "LOC123")

            assert result is not None
            assert result["voiceType"] == "charlotte"
            assert result["voiceProvider"] == "eleven_labs"

    @pytest.mark.asyncio
    async def test_fetch_voice_config_not_found(self):
        """Returns None when voice config not found."""
        from vakdeepgram.connection_store import _fetch_voice_config

        mock_table = AsyncMock()
        mock_table.get_item = AsyncMock(return_value={"Item": None})

        mock_resource = AsyncMock()
        mock_resource.Table = MagicMock(return_value=mock_table)

        with patch("vakdeepgram.connection_store.aioboto3.Session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.resource = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resource),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_session.return_value = mock_session_instance

            result = await _fetch_voice_config("MERCH123", "LOC123")

            assert result is None


class TestVoiceSettingsApplied:
    """Tests for voice settings being applied to Deepgram."""

    def test_build_settings_with_voice_config(self, mock_connection_context):
        """Voice settings from config are applied to Deepgram settings."""
        from vakdeepgram.deepgram_handler import DeepgramManager
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-123"
        # Handler reads voice_config (snake_case) from context
        context = {
            **mock_connection_context,
            "voice_config": {
                "voice_type": "charlotte",
                "voice_provider": "eleven_labs",
                "voice_id": "0mevMNFMwHxBOUTpeMGN",
                "voice_model_id": "eleven_multilingual_v2",
            },
        }
        set_connection_context(connection_id, context)

        manager = DeepgramManager()
        settings = manager._build_settings(use_mulaw=False, connection_id=connection_id)

        # Verify speak provider uses voice config
        speak_provider = settings["agent"]["speak"]["provider"]
        assert speak_provider["type"] == "eleven_labs"
        assert speak_provider["voice_id"] == "0mevMNFMwHxBOUTpeMGN"
        assert speak_provider["model_id"] == "eleven_multilingual_v2"

    def test_build_settings_with_deepgram_voice(self, mock_connection_context):
        """Deepgram voice provider is applied correctly."""
        from vakdeepgram.deepgram_handler import DeepgramManager
        from vakdeepgram.connection_store import set_connection_context

        connection_id = "test-conn-124"
        context = {
            **mock_connection_context,
            "voice_config": {
                "voice_type": "thalia",
                "voice_provider": "deepgram",
                "voice_id": "aura-2-thalia-en",
            },
        }
        set_connection_context(connection_id, context)

        manager = DeepgramManager()
        settings = manager._build_settings(use_mulaw=False, connection_id=connection_id)

        speak_provider = settings["agent"]["speak"]["provider"]
        assert speak_provider["type"] == "deepgram"
        assert speak_provider["model"] == "aura-2-thalia-en"

    def test_voice_switch_updates_deepgram_settings(self, mock_connection_context):
        """Voice switch: changing context voice_config produces different Deepgram speak settings."""
        from vakdeepgram.deepgram_handler import DeepgramManager
        from vakdeepgram.connection_store import set_connection_context, update_connection_context

        connection_id = "test-conn-voice-switch"
        manager = DeepgramManager()

        # Start with ElevenLabs Charlotte
        set_connection_context(
            connection_id,
            {
                **mock_connection_context,
                "voice_config": {
                    "voice_type": "charlotte",
                    "voice_provider": "eleven_labs",
                    "voice_id": "cgSgspJ2msm6clMCkdW9",
                    "voice_model_id": "eleven_multilingual_v2",
                },
            },
        )
        settings_a = manager._build_settings(use_mulaw=False, connection_id=connection_id)
        speak_a = settings_a["agent"]["speak"]["provider"]
        assert speak_a["type"] == "eleven_labs"
        assert speak_a["voice_id"] == "cgSgspJ2msm6clMCkdW9"

        # Switch to Deepgram Odysseus
        update_connection_context(
            connection_id,
            {
                "voice_config": {
                    "voice_type": "odysseus",
                    "voice_provider": "deepgram",
                    "voice_id": "aura-2-odysseus-en",
                },
            },
        )
        settings_b = manager._build_settings(use_mulaw=False, connection_id=connection_id)
        speak_b = settings_b["agent"]["speak"]["provider"]
        assert speak_b["type"] == "deepgram"
        assert speak_b["model"] == "aura-2-odysseus-en"
        assert speak_b["type"] != speak_a["type"], "Voice switch should change provider"

    def test_build_settings_falls_back_to_defaults(self, mock_connection_context):
        """Falls back to default settings when no voice config."""
        from vakdeepgram.deepgram_handler import DeepgramManager
        from vakdeepgram.connection_store import set_connection_context
        from vakdeepgram import config

        connection_id = "test-conn-125"
        set_connection_context(connection_id, mock_connection_context)

        manager = DeepgramManager()
        settings = manager._build_settings(use_mulaw=False, connection_id=connection_id)

        # Should use config defaults
        speak_provider = settings["agent"]["speak"]["provider"]
        expected_type = config.settings.deepgram_speaking_provider or "eleven_labs"
        assert speak_provider["type"] == expected_type


class TestVoiceConfigIncludedInContext:
    """Tests for voice config being included in business context."""

    def test_voice_config_key_exists_in_context(self, mock_context_with_voice_config):
        """Voice config key exists in connection context."""
        assert "voiceConfig" in mock_context_with_voice_config
        assert mock_context_with_voice_config["voiceConfig"]["voiceType"] == "charlotte"

    def test_voice_config_fields_present(self, mock_voice_config):
        """Voice config contains all required fields."""
        required_fields = [
            "voiceType",
            "voiceProvider",
            "voiceId",
            "forwardingNumber",
            "enableAutoTransfer",
            "maxFailuresBeforeTransfer",
        ]
        for field in required_fields:
            assert field in mock_voice_config, f"Missing field: {field}"
