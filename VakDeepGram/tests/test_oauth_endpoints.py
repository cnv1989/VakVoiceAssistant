import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vakdeepgram.main import app


@pytest.mark.asyncio
async def test_voice_oauth_connect_success(monkeypatch):
    async def _fake_resolve_context(business_number: str, caller_number=None):
        assert business_number == "+15104054454"
        assert caller_number == "+15105550000"
        return {
            "success": True,
            "provider": "setmore",
            "location": {"business_name": "Mission Barber"},
        }

    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {
            "success": True,
            "claims": {"sub": "user-123", "business_number": "+15104054454"},
        },
    )
    monkeypatch.setattr("vakdeepgram.main.resolve_context_for_request", _fake_resolve_context)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/voice/oauth/connect",
            headers={
                "Authorization": "Bearer valid-token",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "integrin.example",
            },
            json={
                "business_number": "+15104054454",
                "customer_number": "+15105550000",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["oauth_subject"] == "user-123"
    assert body["websocket_url"].startswith(
        "wss://integrin.example/ws?businessNumber=%2B15104054454&customerPhone=%2B15105550000"
    )
    assert "access_token=valid-token" in body["websocket_url"]
    assert body["business_context"]["provider"] == "setmore"


@pytest.mark.asyncio
async def test_voice_oauth_connect_business_mismatch(monkeypatch):
    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {"success": True, "claims": {"sub": "user-123", "business_number": "+19999999999"}},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/voice/oauth/connect",
            headers={"Authorization": "Bearer valid-token"},
            json={"business_number": "+15104054454"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_oauth_requires_bearer_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/oauth",
            json={"message": "hi", "business_number": "+15104054454"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_oauth_success(monkeypatch):
    async def _fake_chat(request, oauth_auth):
        assert oauth_auth["claims"]["sub"] == "user-123"
        payload = await request.json()
        assert payload["business_number"] == "+15104054454"
        return {"reply": "ok", "model_id": "test-model"}

    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {
            "success": True,
            "claims": {"sub": "user-123", "business_number": "+15104054454"},
        },
    )
    monkeypatch.setattr("vakdeepgram.main.chat", _fake_chat)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/oauth",
            headers={"Authorization": "Bearer valid-token"},
            json={"message": "hello", "business_number": "+15104054454"},
        )

    assert response.status_code == 200
    assert response.json()["reply"] == "ok"


@pytest.mark.asyncio
async def test_chat_requires_oauth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat",
            json={"message": "hello", "business_number": "+15104054454"},
        )
    assert response.status_code == 401


def test_ws_requires_oauth_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?businessNumber=%2B15104054454"):
            pass
