"""
End-to-end tests for /chat, /whatsapp-chat endpoints and
UserBookingLink DynamoDB integration.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from vakdeepgram.main import app


# ── Helpers ──────────────────────────────────────────────────────────────────

BUSINESS_PHONE = "+15550001111"
CUSTOMER_PHONE = "+14155551234"


@pytest.fixture
def twilio_credentials(monkeypatch):
    """Configure Twilio credentials for endpoints that send a reply.

    /twilio-chat and /whatsapp-chat refuse to send without these and return an
    error response, so any test asserting a 200 needs them set.
    """
    from vakdeepgram import config

    monkeypatch.setattr(config.settings, "twilio_account_sid", "ACtestsid", raising=False)
    monkeypatch.setattr(config.settings, "twilio_auth_token", "test-auth-token", raising=False)


FAKE_BUSINESS_CONTEXT = {
    "success": True,
    "provider": "setmore",
    "phone_number": BUSINESS_PHONE,
    "location": {
        "business_name": "Test Business",
        "timezone": "America/Los_Angeles",
        "phone_number": BUSINESS_PHONE,
    },
    "services": [
        {
            "key": "svc1",
            "serviceName": "Haircut",
            "duration": 30,
        }
    ],
    "staff": [{"key": "staff1", "firstName": "Alex"}],
}


def _fake_oauth_valid(token):
    return {
        "success": True,
        "claims": {"sub": "user-123", "business_number": BUSINESS_PHONE},
    }


async def _fake_resolve_context(business_number, caller_number=None, **kwargs):
    if business_number == BUSINESS_PHONE:
        return dict(FAKE_BUSINESS_CONTEXT)
    return {"success": False, "error": "Unknown business"}


def _mock_agent_call(msg):
    """Simulate Strands Agent __call__ returning a simple reply."""
    return "Hello! How can I help you today?"


# ── /chat endpoint tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_returns_reply(monkeypatch):
    """POST /chat with valid payload returns agent reply."""
    monkeypatch.setattr("vakdeepgram.main.validate_oauth_token", _fake_oauth_valid)
    monkeypatch.setattr("vakdeepgram.main.resolve_context_for_request", _fake_resolve_context)

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.return_value = "Hello! How can I help you today?"
    mock_agent_instance.state = {}
    mock_agent_cls.return_value = mock_agent_instance
    monkeypatch.setattr("vakdeepgram.main.Agent", mock_agent_cls)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat",
            headers={"Authorization": "Bearer valid-token"},
            json={
                "message": "What services do you offer?",
                "business_number": BUSINESS_PHONE,
                "customer_phone": CUSTOMER_PHONE,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert body["reply"] == "Hello! How can I help you today?"


@pytest.mark.asyncio
async def test_chat_requires_message(monkeypatch):
    """POST /chat without message returns 400."""
    monkeypatch.setattr("vakdeepgram.main.validate_oauth_token", _fake_oauth_valid)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat",
            headers={"Authorization": "Bearer valid-token"},
            json={"business_number": BUSINESS_PHONE},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_requires_business_number(monkeypatch):
    """POST /chat without business_number or account_id returns 400."""
    monkeypatch.setattr("vakdeepgram.main.validate_oauth_token", _fake_oauth_valid)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat",
            headers={"Authorization": "Bearer valid-token"},
            json={"message": "hi"},
        )
    assert response.status_code == 400


# ── /whatsapp-chat endpoint tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_whatsapp_chat_with_booking_link_lookup(monkeypatch, twilio_credentials):
    """WhatsApp chat resolves business from UserBookingLink when To is the shared WA number."""
    monkeypatch.setattr("vakdeepgram.main.verify_twilio_http_signature", lambda req, body: True)
    monkeypatch.setattr("vakdeepgram.main.resolve_context_for_request", _fake_resolve_context)

    # Mock booking link lookup — returns the business phone
    async def _fake_get_latest_booking_link(*, table_name, customer_phone, aws_region):
        if customer_phone == CUSTOMER_PHONE:
            return {
                "customerPhone": CUSTOMER_PHONE,
                "businessPhone": BUSINESS_PHONE,
                "bookingUrl": "https://booking.setmore.com/test",
                "createdAt": "2026-03-23T10:00:00Z",
            }
        return None

    monkeypatch.setattr("vakdeepgram.main.get_latest_booking_link", _fake_get_latest_booking_link)

    # Mock Agent
    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.__call__ = _mock_agent_call
    mock_agent_instance.state = {}
    mock_agent_cls.return_value = mock_agent_instance
    monkeypatch.setattr("vakdeepgram.main.Agent", mock_agent_cls)

    # Mock Twilio client for sending reply
    mock_twilio_cls = MagicMock()
    mock_twilio_instance = MagicMock()
    mock_message = MagicMock()
    mock_message.sid = "SM_test_123"
    mock_twilio_instance.messages.create.return_value = mock_message
    mock_twilio_cls.return_value = mock_twilio_instance
    monkeypatch.setattr("vakdeepgram.main.TwilioClient", mock_twilio_cls)

    # Simulate Twilio form-encoded WhatsApp webhook
    form_body = (
        f"Body=Hi+I+got+a+booking+link"
        f"&To=whatsapp%3A%2B14155238886"
        f"&From=whatsapp%3A{CUSTOMER_PHONE.replace('+', '%2B')}"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/whatsapp-chat",
            content=form_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    # Verify Twilio was called with whatsapp: prefixed numbers
    call_kwargs = mock_twilio_instance.messages.create.call_args
    assert call_kwargs.kwargs["from_"].startswith("whatsapp:")
    assert call_kwargs.kwargs["to"].startswith("whatsapp:")


@pytest.mark.asyncio
async def test_whatsapp_chat_no_booking_link_falls_back(monkeypatch, twilio_credentials):
    """When no booking link found, falls back to WhatsApp number as business."""
    monkeypatch.setattr("vakdeepgram.main.verify_twilio_http_signature", lambda req, body: True)
    monkeypatch.setattr("vakdeepgram.main.resolve_context_for_request", _fake_resolve_context)

    # No booking link found
    async def _fake_get_latest_none(*, table_name, customer_phone, aws_region):
        return None

    monkeypatch.setattr("vakdeepgram.main.get_latest_booking_link", _fake_get_latest_none)

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.__call__ = _mock_agent_call
    mock_agent_instance.state = {}
    mock_agent_cls.return_value = mock_agent_instance
    monkeypatch.setattr("vakdeepgram.main.Agent", mock_agent_cls)

    mock_twilio_cls = MagicMock()
    mock_twilio_instance = MagicMock()
    mock_message = MagicMock()
    mock_message.sid = "SM_test_456"
    mock_twilio_instance.messages.create.return_value = mock_message
    mock_twilio_cls.return_value = mock_twilio_instance
    monkeypatch.setattr("vakdeepgram.main.TwilioClient", mock_twilio_cls)

    form_body = (
        f"Body=Hello"
        f"&To=whatsapp%3A%2B14155238886"
        f"&From=whatsapp%3A%2B19995551111"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/whatsapp-chat",
            content=form_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    # Should still work (falls back to +14155238886 as business)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_whatsapp_chat_requires_from(monkeypatch):
    """WhatsApp chat returns 400 when From (customer phone) is missing."""
    monkeypatch.setattr("vakdeepgram.main.verify_twilio_http_signature", lambda req, body: True)

    form_body = "Body=Hello&To=whatsapp%3A%2B14155238886"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/whatsapp-chat",
            content=form_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_whatsapp_chat_requires_body(monkeypatch):
    """WhatsApp chat returns 400 when Body (message) is missing."""
    monkeypatch.setattr("vakdeepgram.main.verify_twilio_http_signature", lambda req, body: True)

    form_body = f"To=whatsapp%3A%2B14155238886&From=whatsapp%3A{CUSTOMER_PHONE.replace('+', '%2B')}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/whatsapp-chat",
            content=form_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400


# ── BookingLink utility tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_booking_link():
    """write_booking_link writes correct item to DynamoDB."""
    from utils.booking_links import write_booking_link

    mock_table = AsyncMock()
    mock_ddb = AsyncMock()
    mock_ddb.Table = AsyncMock(return_value=mock_table)

    mock_session = MagicMock()
    mock_resource_cm = AsyncMock()
    mock_resource_cm.__aenter__ = AsyncMock(return_value=mock_ddb)
    mock_resource_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.resource.return_value = mock_resource_cm

    with patch("utils.booking_links.aioboto3.Session", return_value=mock_session):
        result = await write_booking_link(
            table_name="UserBookingLink-Alpha",
            customer_phone=CUSTOMER_PHONE,
            business_phone=BUSINESS_PHONE,
            booking_url="https://booking.setmore.com/test",
            service_name="Haircut",
            staff_name="Alex",
            channel="sms+whatsapp",
        )

    assert result is True
    mock_table.put_item.assert_awaited_once()
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["customerPhone"] == CUSTOMER_PHONE
    assert item["businessPhone"] == BUSINESS_PHONE
    assert item["bookingUrl"] == "https://booking.setmore.com/test"
    assert item["serviceName"] == "Haircut"
    assert item["staffName"] == "Alex"
    assert item["channel"] == "sms+whatsapp"
    assert "createdAt" in item
    assert "ttl" in item


@pytest.mark.asyncio
async def test_get_latest_booking_link():
    """get_latest_booking_link queries DynamoDB and returns the latest item."""
    from utils.booking_links import get_latest_booking_link

    expected_item = {
        "customerPhone": CUSTOMER_PHONE,
        "businessPhone": BUSINESS_PHONE,
        "bookingUrl": "https://booking.setmore.com/latest",
        "createdAt": "2026-03-23T12:00:00Z",
    }

    mock_table = AsyncMock()
    mock_table.query = AsyncMock(return_value={"Items": [expected_item]})
    mock_ddb = AsyncMock()
    mock_ddb.Table = AsyncMock(return_value=mock_table)

    mock_session = MagicMock()
    mock_resource_cm = AsyncMock()
    mock_resource_cm.__aenter__ = AsyncMock(return_value=mock_ddb)
    mock_resource_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.resource.return_value = mock_resource_cm

    with patch("utils.booking_links.aioboto3.Session", return_value=mock_session):
        result = await get_latest_booking_link(
            table_name="UserBookingLink-Alpha",
            customer_phone=CUSTOMER_PHONE,
        )

    assert result is not None
    assert result["businessPhone"] == BUSINESS_PHONE
    assert result["bookingUrl"] == "https://booking.setmore.com/latest"

    # Verify query params: newest first, limit 1
    query_kwargs = mock_table.query.call_args.kwargs
    assert query_kwargs["ScanIndexForward"] is False
    assert query_kwargs["Limit"] == 1


@pytest.mark.asyncio
async def test_get_latest_booking_link_no_results():
    """get_latest_booking_link returns None when no records exist."""
    from utils.booking_links import get_latest_booking_link

    mock_table = AsyncMock()
    mock_table.query = AsyncMock(return_value={"Items": []})
    mock_ddb = AsyncMock()
    mock_ddb.Table = AsyncMock(return_value=mock_table)

    mock_session = MagicMock()
    mock_resource_cm = AsyncMock()
    mock_resource_cm.__aenter__ = AsyncMock(return_value=mock_ddb)
    mock_resource_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.resource.return_value = mock_resource_cm

    with patch("utils.booking_links.aioboto3.Session", return_value=mock_session):
        result = await get_latest_booking_link(
            table_name="UserBookingLink-Alpha",
            customer_phone="+19999999999",
        )

    assert result is None
