"""
Pytest fixtures for VakDeepGram tests
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment variables before importing config
os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")
os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture
def mock_square_response_success():
    """Mock successful Square API response."""
    response = MagicMock()
    response.is_error.return_value = False
    response.body = {"customer": {"id": "CUST123", "given_name": "John"}}
    return response


@pytest.fixture
def mock_square_response_error():
    """Mock error Square API response."""
    response = MagicMock()
    response.is_error.return_value = True
    response.errors = [{"code": "NOT_FOUND", "detail": "Customer not found"}]
    return response


@pytest.fixture
def mock_connection_context():
    """Mock connection context."""
    return {
        "success": True,
        "businessNumber": "5551234567",
        "locationId": "LOC123",
        "merchantId": "MERCH123",
        "userId": "USER123",
        "accessToken": "sq0-test-token",
        "location": {
            "id": "LOC123",
            "name": "Test Location",
            "timezone": "America/Los_Angeles",
            "phone_number": "+15551234567",
        },
        "services": [
            {
                "id": "SVC1",
                "item_data": {
                    "name": "Haircut",
                    "variations": [
                        {
                            "id": "VAR1",
                            "item_variation_data": {
                                "name": "Regular",
                                "service_duration": 1800000,  # 30 minutes
                            },
                            "version": 1,
                        }
                    ],
                },
            }
        ],
        "staff": [
            {
                "id": "STAFF1",
                "status": "ACTIVE",
                "given_name": "Alex",
                "family_name": "Smith",
            }
        ],
    }


@pytest.fixture
def mock_deepgram_session():
    """Mock Deepgram session."""
    session = MagicMock()
    session.connection_id = "test-conn-123"
    session.is_active = True
    session.is_ready = True
    session.use_mulaw = False
    session.sts_ws = AsyncMock()
    session.send_to_client = AsyncMock()
    session.audio_buffer = []
    session.max_audio_buffer_size = 100
    return session
