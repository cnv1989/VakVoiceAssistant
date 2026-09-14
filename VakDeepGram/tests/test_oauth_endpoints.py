import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vakdeepgram.main import app


@pytest.mark.asyncio
async def test_voice_oauth_connect_success(monkeypatch):
    """/voice/oauth/connect hands back a signed WebSocket URL.

    It deliberately does not resolve business context itself — /ws does that
    from the businessNumber query param, so there is a single resolution path
    and no stale cached context. Hence no business_context in the response.
    """
    resolve_calls = []

    async def _fail_if_resolved(*args, **kwargs):
        resolve_calls.append(args)
        raise AssertionError("connect should not pre-resolve business context")

    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {
            "success": True,
            "claims": {"sub": "user-123", "business_number": "+15550001111"},
        },
    )
    monkeypatch.setattr("vakdeepgram.main.resolve_context_for_request", _fail_if_resolved)

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
                "business_number": "+15550001111",
                "customer_number": "+15105550000",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["oauth_subject"] == "user-123"
    assert body["websocket_url"].startswith(
        "wss://integrin.example/ws?businessNumber=%2B15550001111&customerPhone=%2B15105550000"
    )
    assert "access_token=valid-token" in body["websocket_url"]
    assert body["business_number"] == "+15550001111"
    assert body["customer_number"] == "+15105550000"
    assert resolve_calls == []


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
            json={"business_number": "+15550001111"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_oauth_requires_bearer_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/oauth",
            json={"message": "hi", "business_number": "+15550001111"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_oauth_success(monkeypatch):
    async def _fake_chat(request, oauth_auth):
        assert oauth_auth["claims"]["sub"] == "user-123"
        payload = await request.json()
        assert payload["business_number"] == "+15550001111"
        return {"reply": "ok", "model_id": "test-model"}

    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {
            "success": True,
            "claims": {"sub": "user-123", "business_number": "+15550001111"},
        },
    )
    monkeypatch.setattr("vakdeepgram.main.chat", _fake_chat)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/oauth",
            headers={"Authorization": "Bearer valid-token"},
            json={"message": "hello", "business_number": "+15550001111"},
        )

    assert response.status_code == 200
    assert response.json()["reply"] == "ok"


@pytest.mark.asyncio
async def test_chat_requires_oauth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat",
            json={"message": "hello", "business_number": "+15550001111"},
        )
    assert response.status_code == 401


def test_ws_requires_oauth_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?businessNumber=%2B15550001111"):
            pass


def test_ws_unauth_voice_localhost_bypass(monkeypatch):
    """Deepgram 'unauth' voice API: /ws accepts without token when Host is localhost and OAUTH_ALLOW_LOCALHOST_NOAUTH=true."""
    monkeypatch.setattr(
        "vakdeepgram.main.config.settings.oauth_allow_localhost_noauth",
        True,
    )
    # _validate_websocket_oauth should allow connection (no token) for localhost
    from vakdeepgram.main import _validate_websocket_oauth

    query_params = {"businessNumber": "+15550001111"}
    headers = {"Host": "localhost"}
    is_valid, error, _ = _validate_websocket_oauth(query_params, headers)
    assert is_valid is True, f"Expected localhost unauth bypass, got error: {error}"

    # Non-localhost without token should still require auth
    headers_remote = {"Host": "vak.example.com"}
    is_valid_remote, error_remote, _ = _validate_websocket_oauth(query_params, headers_remote)
    assert is_valid_remote is False
    assert "Bearer" in (error_remote or "")


@pytest.mark.asyncio
async def test_hello(monkeypatch):
    """Smoke test: chat with message 'hello' (used by Slack task 'test hello')."""
    async def _fake_chat(request, oauth_auth):
        payload = await request.json()
        assert payload.get("message") == "hello"
        return {"reply": "ok", "model_id": "test-model"}

    monkeypatch.setattr(
        "vakdeepgram.main.validate_oauth_token",
        lambda token: {
            "success": True,
            "claims": {"sub": "user-123", "business_number": "+15550001111"},
        },
    )
    monkeypatch.setattr("vakdeepgram.main.chat", _fake_chat)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/oauth",
            headers={"Authorization": "Bearer valid-token"},
            json={"message": "hello", "business_number": "+15550001111"},
        )
    assert response.status_code == 200
    assert response.json()["reply"] == "ok"
