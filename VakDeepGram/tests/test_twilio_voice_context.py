"""
Integration tests for Twilio voice path: business context resolution.

- Unit tests for _parse_twilio_start_event (mimics Twilio payload shapes).
- Integration test that sends Twilio-like WebSocket start event and validates
  business context is resolved (mocked resolve to avoid DynamoDB).

To inspect the actual Twilio payload in AWS: check CloudWatch Logs for the
VakDeepGram service and search for "Twilio start event full payload" (logged at
INFO for every /twilio start event). That shows the exact JSON Twilio sends so
you can align customParameters or fallbacks if needed.
"""
from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

# Import after path setup if needed
from vakdeepgram.main import _parse_twilio_start_event


# ─── Unit tests: parse Twilio start event ───────────────────────────────────


def test_parse_twilio_start_event_custom_parameters_called_caller():
    """Twilio sends To/Called and From/Caller in start.customParameters (TwiML <Parameter>)."""
    payload = {
        "event": "start",
        "sequenceNumber": "1",
        "start": {
            "accountSid": "ACxx",
            "streamSid": "MZxx",
            "callSid": "CAxx",
            "tracks": ["inbound"],
            "customParameters": {
                "Called": "+15104054454",
                "Caller": "+15105551234",
                "Service": "voice",
            },
        },
        "streamSid": "MZxx",
    }
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] == "+15104054454"
    assert out["from_number"] == "+15105551234"
    assert out["stream_sid"] == "MZxx"
    assert out["call_sid"] == "CAxx"
    assert out["account_sid"] == "ACxx"
    assert out["service_name"] == "voice"


def test_parse_twilio_start_event_custom_parameters_to_from():
    """Some setups use To/From instead of Called/Caller."""
    payload = {
        "event": "start",
        "start": {
            "streamSid": "MZyy",
            "callSid": "CAyy",
            "accountSid": "ACyy",
            "customParameters": {
                "To": "+15551234567",
                "From": "+15559876543",
            },
        },
    }
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] == "+15551234567"
    assert out["from_number"] == "+15559876543"
    assert out["stream_sid"] == "MZyy"


def test_parse_twilio_start_event_root_level_fallback():
    """Fallback to root-level To, From, streamSid, callSid, accountSid."""
    payload = {
        "event": "start",
        "streamSid": "MZroot",
        "To": "+15101112222",
        "From": "+15103334444",
        "callSid": "CAroot",
        "accountSid": "ACroot",
        "start": {"tracks": ["inbound"]},
    }
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] == "+15101112222"
    assert out["from_number"] == "+15103334444"
    assert out["stream_sid"] == "MZroot"
    assert out["call_sid"] == "CAroot"
    assert out["account_sid"] == "ACroot"


def test_parse_twilio_start_event_lowercase_custom_params():
    """customParameters keys may be lowercased by some proxies."""
    payload = {
        "event": "start",
        "start": {
            "streamSid": "MZzz",
            "customParameters": {
                "called": "+15551111111",
                "caller": "+15552222222",
            },
        },
    }
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] == "+15551111111"
    assert out["from_number"] == "+15552222222"
    assert out["stream_sid"] == "MZzz"


def test_parse_twilio_start_event_empty_start():
    """Handle missing or empty start."""
    payload = {"event": "start", "streamSid": "MZonly", "To": "+15550000000", "From": "+15551111111"}
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] == "+15550000000"
    assert out["from_number"] == "+15551111111"
    assert out["stream_sid"] == "MZonly"
    assert out["call_sid"] is None
    assert out["account_sid"] is None


def test_parse_twilio_start_event_no_business_number():
    """When To/Called are missing, to_number is None."""
    payload = {
        "event": "start",
        "start": {
            "streamSid": "MZnn",
            "callSid": "CAnn",
            "accountSid": "ACnn",
            "customParameters": {"From": "+15559999999"},
        },
    }
    out = _parse_twilio_start_event(payload)
    assert out["to_number"] is None
    assert out["from_number"] == "+15559999999"


# ─── Integration test: /twilio WebSocket + business context ─────────────────


@pytest.mark.asyncio
async def test_twilio_voice_start_resolves_business_context():
    """
    Connect to /twilio, send Twilio-like connected + start (with business number
    in customParameters), then stop. Assert resolve_and_store_connection_context
    was called with the expected business_number and extra_context.
    """
    from fastapi.testclient import TestClient

    from vakdeepgram.api.main import app

    business_number = "+15104054454"
    caller_number = "+15105550000"
    stream_sid = f"MZ{uuid.uuid4().hex[:12]}"
    call_sid = f"CA{uuid.uuid4().hex[:8]}"
    account_sid = "ACtestaccount"

    start_payload = {
        "event": "start",
        "sequenceNumber": "1",
        "start": {
            "streamSid": stream_sid,
            "accountSid": account_sid,
            "callSid": call_sid,
            "tracks": ["inbound"],
            "customParameters": {
                "Called": business_number,
                "Caller": caller_number,
                "Service": "voice-test",
            },
        },
        "streamSid": stream_sid,
    }

    captured_connection_id = []
    captured_business_number = []
    captured_extra = []

    async def fake_resolve(connection_id: str, business_number_arg: str, *, extra_context: dict | None = None):
        captured_connection_id.append(connection_id)
        captured_business_number.append(business_number_arg)
        captured_extra.append(extra_context or {})
        return {"success": True, "businessNumber": business_number_arg, **(extra_context or {})}

    with patch(
        "vakdeepgram.main.resolve_and_store_connection_context",
        new_callable=AsyncMock,
        side_effect=fake_resolve,
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/twilio") as ws:
                ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
                ws.send_json(start_payload)
                # Send one media chunk so server processes start
                ws.send_json(
                    {
                        "event": "media",
                        "media": {
                            "track": "inbound",
                            "payload": base64.b64encode(bytes([0xFF] * 160)).decode("ascii"),
                        },
                    }
                )
                ws.send_json({"event": "stop"})

    assert len(captured_connection_id) >= 1, "resolve_and_store_connection_context should be called after start"
    assert captured_business_number[0] == business_number
    assert captured_connection_id[0].startswith("twilio-")
    extra = captured_extra[0]
    assert extra.get("caller") == caller_number
    assert extra.get("called") == business_number
    assert extra.get("callSid") == call_sid
    assert extra.get("accountSid") == account_sid
