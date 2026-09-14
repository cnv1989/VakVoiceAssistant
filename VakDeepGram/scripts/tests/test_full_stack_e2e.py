#!/usr/bin/env python3
"""
Full-stack integration test for business +15550001111.

Coverage:
1. Provider context + provider clients
2. Available Strands tools
3. Deepgram function definitions
4. E2E /chat experience
5. E2E browser voice (/ws)
6. E2E Twilio voice stream (/twilio)

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_full_stack_e2e --base-url http://localhost:8080
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
from typing import Any, Dict
from urllib.parse import urlencode, urlparse

import httpx
import websockets

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

from vakdeepgram.connection_store import resolve_business_context
from providers import get_tools_for_provider
from providers.clients import (
    SetmoreApiClient,
    SquareApiClient,
    ensure_provider_access_context,
)
from vakdeepgram.agent_functions import get_function_definitions_for_provider
from utils.square_helpers import parse_square_response

BUSINESS_NUMBER = "+15550001111"
DEFAULT_BASE_URL = "http://localhost:8080"


def _to_ws_url(base_url: str, path: str, query: Dict[str, Any] | None = None) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    q = f"?{urlencode(query)}" if query else ""
    return f"{scheme}://{parsed.netloc}{path}{q}"


async def _test_provider_clients_and_catalog() -> tuple[str, dict]:
    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        raise RuntimeError(f"resolve_business_context failed: {context.get('error')}")
    provider = (context.get("provider") or "square").lower()
    auth = await ensure_provider_access_context(
        business_context=context,
        require_location=(provider == "square"),
    )
    if not auth.get("success"):
        raise RuntimeError(f"ensure_provider_access_context failed: {auth.get('error')}")

    if provider == "setmore":
        setmore_client = SetmoreApiClient(
            auth["access_token"],
            refresh_token=auth.get("refresh_token"),
        )
        services = await setmore_client.fetch_services()
        staff = await setmore_client.fetch_staff()
        if not services.get("success"):
            raise RuntimeError(f"Setmore fetch_services failed: {services.get('error')}")
        if not staff.get("success"):
            raise RuntimeError(f"Setmore fetch_staff failed: {staff.get('error')}")
        print(f"  Setmore services: {len(services.get('services') or [])}")
        print(f"  Setmore staff: {len(staff.get('staffs') or [])}")
    else:
        square_client = SquareApiClient(auth["access_token"])
        locations_response = await square_client.locations.list()
        parsed = parse_square_response(locations_response)
        if not parsed.get("success"):
            raise RuntimeError(f"Square locations.list failed: {parsed.get('error')}")
        locations = parsed.get("payload", {}).get("locations") or []
        print(f"  Square locations: {len(locations)}")
        print(f"  Square location_id: {auth.get('location_id')}")

    return provider, context


def _test_tools_and_functions(provider: str) -> None:
    tools = get_tools_for_provider(provider)
    tool_names = sorted(getattr(t, "__name__", str(t)) for t in tools)
    functions = get_function_definitions_for_provider(provider)
    fn_names = sorted((f.get("name") or "?") for f in functions)
    if not tool_names:
        raise RuntimeError(f"No tools found for provider={provider}")
    if not fn_names:
        raise RuntimeError(f"No Deepgram functions found for provider={provider}")
    print(f"  Tools ({len(tool_names)}): {', '.join(tool_names)}")
    print(f"  Deepgram fns ({len(fn_names)}): {', '.join(fn_names)}")


async def _test_chat_e2e(base_url: str, oauth_token: str) -> None:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {oauth_token}"}

    session_id = f"e2e-chat-{uuid.uuid4().hex[:10]}"
    async with httpx.AsyncClient(timeout=120) as client:
        for message in (
            "Hi, what services do you offer?",
            "Are you open on Sunday?",
        ):
            payload = {
                "business_number": BUSINESS_NUMBER,
                "customer_number": "+15105550000",
                "session_id": session_id,
                "message": message,
            }
            response = await client.post(f"{base_url.rstrip('/')}/chat", json=payload, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"/chat returned {response.status_code}: {response.text[:500]}")
            body = response.json()
            reply = body.get("reply")
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError(f"/chat missing reply payload: {json.dumps(body)[:500]}")
            if message.startswith("Are you open"):
                low = reply.lower()
                if "sunday" not in low and "closed" not in low and "open" not in low:
                    raise RuntimeError(f"/chat hours response did not mention hours status: {reply[:300]}")
            print(f"  /chat reply chars ({message[:20]}...): {len(reply)}")


async def _recv_json_with_timeout(ws, timeout_s: float = 8.0) -> dict | None:
    try:
        msg = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None
    if isinstance(msg, (bytes, bytearray)):
        return None
    try:
        return json.loads(msg)
    except Exception:
        return None


async def _test_browser_voice_e2e(base_url: str, oauth_token: str) -> None:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {oauth_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/voice/oauth/connect",
            json={"business_number": BUSINESS_NUMBER, "customer_number": "+15105550000"},
            headers=headers,
        )
    if response.status_code != 200:
        raise RuntimeError(f"/voice/oauth/connect returned {response.status_code}: {response.text[:500]}")
    body = response.json()
    ws_url = body.get("websocket_url")
    if not ws_url:
        raise RuntimeError(f"/voice/oauth/connect missing websocket_url: {json.dumps(body)[:500]}")

    async with websockets.connect(ws_url, close_timeout=3) as ws:
        message_types = set()
        for _ in range(8):
            data = await _recv_json_with_timeout(ws, timeout_s=4.0)
            if not data:
                continue
            msg_type = data.get("type")
            if msg_type:
                message_types.add(msg_type)
            if "deepgram-ready" in message_types:
                break

        if "deepgram-ready" not in message_types:
            raise RuntimeError(f"/ws did not reach deepgram-ready. seen={sorted(message_types)}")

        await ws.send(json.dumps({"action": "start-recording"}))
        silence = (b"\x00\x00") * 9600
        await ws.send(silence)
        await asyncio.sleep(0.3)
    print("  /ws voice handshake passed")


async def _test_twilio_voice_e2e(base_url: str) -> None:
    ws_url = _to_ws_url(base_url, "/twilio")
    async with websockets.connect(ws_url, close_timeout=3) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": f"MZ{uuid.uuid4().hex[:12]}",
                        "accountSid": "ACtest",
                        "callSid": f"CAtest{uuid.uuid4().hex[:8]}",
                        "customParameters": {
                            "Called": BUSINESS_NUMBER,
                            "Caller": "+15105550000",
                            "Service": "voice-test",
                        },
                    },
                }
            )
        )
        mulaw_silence = bytes([0xFF] * 160)
        await ws.send(
            json.dumps(
                {
                    "event": "media",
                    "media": {
                        "track": "inbound",
                        "payload": base64.b64encode(mulaw_silence).decode("ascii"),
                    },
                }
            )
        )
        await ws.send(json.dumps({"event": "stop"}))
        await asyncio.sleep(0.3)
    print("  /twilio voice stream handshake passed")


async def main(args: argparse.Namespace) -> int:
    print(f"=== Full stack E2E for {BUSINESS_NUMBER} ===")
    print(f"Base URL: {args.base_url}")
    failures = 0

    print("\n[1] Provider clients")
    provider = "unknown"
    try:
        provider, _ = await _test_provider_clients_and_catalog()
        print(f"  Provider: {provider}")
    except Exception as exc:
        failures += 1
        print(f"  FAIL: {exc}")

    print("\n[2] Strands tools + Deepgram functions")
    try:
        if provider == "unknown":
            raise RuntimeError("Provider was not resolved.")
        _test_tools_and_functions(provider)
    except Exception as exc:
        failures += 1
        print(f"  FAIL: {exc}")

    print("\n[3] /chat E2E")
    try:
        if not args.oauth_token:
            raise RuntimeError("--oauth-token is required for /chat E2E")
        await _test_chat_e2e(args.base_url, args.oauth_token)
    except Exception as exc:
        failures += 1
        print(f"  FAIL: {exc}")

    print("\n[4] /ws voice E2E")
    try:
        if not args.oauth_token:
            raise RuntimeError("--oauth-token is required for /ws voice E2E")
        await _test_browser_voice_e2e(args.base_url, args.oauth_token)
    except Exception as exc:
        failures += 1
        print(f"  FAIL: {exc}")

    if not args.skip_twilio_voice:
        print("\n[5] /twilio voice E2E")
        try:
            await _test_twilio_voice_e2e(args.base_url)
        except Exception as exc:
            failures += 1
            print(f"  FAIL: {exc}")

    print("\n=== Summary ===")
    print(f"Failures: {failures}")
    return 1 if failures else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-stack integration test for clients/tools/functions/chat/voice."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VAKDEEPGRAM_URL", DEFAULT_BASE_URL),
        help=f"VakDeepGram base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--oauth-token",
        default=os.environ.get("VAK_OAUTH_TOKEN"),
        help="OAuth bearer token for /chat and /voice/oauth/connect.",
    )
    parser.add_argument(
        "--skip-twilio-voice",
        action="store_true",
        help="Skip /twilio voice E2E stream check.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_build_parser().parse_args())))
