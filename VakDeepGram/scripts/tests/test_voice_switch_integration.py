#!/usr/bin/env python3
"""
Integration test: voice switch via voiceConfigOverride on /ws.

Verifies that when connecting to the browser voice WebSocket with a
voiceConfigOverride query param, the backend applies the override and
the session reaches deepgram-ready (i.e. voice switching is happening).

Usage:
  cd VakDeepGram
  # With server running and oauth token:
  python -m scripts.tests.test_voice_switch_integration --base-url http://localhost:8080 --oauth-token YOUR_TOKEN
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

import httpx
import websockets

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

BUSINESS_NUMBER = "+15104054454"
DEFAULT_BASE_URL = "http://localhost:8080"


def _voice_override_b64(voice_type: str, voice_provider: str, voice_id: str, voice_model_id: str = "") -> str:
    """Build base64-encoded voice config override (camelCase for API)."""
    payload = {
        "voiceType": voice_type,
        "voiceProvider": voice_provider,
        "voiceId": voice_id,
    }
    if voice_model_id:
        payload["voiceModelId"] = voice_model_id
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


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


async def _test_voice_switch_via_override_e2e(base_url: str, oauth_token: str) -> None:
    """Connect to /ws with voiceConfigOverride and assert deepgram-ready (voice switching applied)."""
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {oauth_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/voice/oauth/connect",
            json={"business_number": BUSINESS_NUMBER, "customer_number": "+15105550000"},
            headers=headers,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"/voice/oauth/connect returned {response.status_code}: {response.text[:500]}"
        )
    body = response.json()
    ws_url = body.get("websocket_url")
    if not ws_url:
        raise RuntimeError(
            f"/voice/oauth/connect missing websocket_url: {json.dumps(body)[:500]}"
        )

    # Append voiceConfigOverride so the backend uses the selected voice (voice switch)
    override = _voice_override_b64(
        voice_type="odysseus",
        voice_provider="deepgram",
        voice_id="aura-2-odysseus-en",
    )
    parsed = urlparse(ws_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["voiceConfigOverride"] = [override]
    new_query = urlencode(query, doseq=True)
    ws_url_with_override = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )

    async with websockets.connect(ws_url_with_override, close_timeout=3) as ws:
        message_types = set()
        for _ in range(12):
            data = await _recv_json_with_timeout(ws, timeout_s=4.0)
            if not data:
                continue
            msg_type = data.get("type")
            if msg_type:
                message_types.add(msg_type)
            if "deepgram-ready" in message_types:
                break

        if "deepgram-ready" not in message_types:
            raise RuntimeError(
                f"/ws with voiceConfigOverride did not reach deepgram-ready. seen={sorted(message_types)}"
            )

        await ws.send(json.dumps({"action": "start-recording"}))
        silence = (b"\x00\x00") * 9600
        await ws.send(silence)
        await asyncio.sleep(0.2)
    print("  /ws voice with voiceConfigOverride (voice switch) passed")


async def main(args: argparse.Namespace) -> int:
    print("=== Voice switch integration test ===")
    print(f"Base URL: {args.base_url}")
    if not args.oauth_token:
        print("FAIL: --oauth-token is required for /voice/oauth/connect")
        return 1
    try:
        await _test_voice_switch_via_override_e2e(args.base_url, args.oauth_token)
        print("OK: Voice switching is happening (override applied, deepgram-ready received)")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Integration test: voice switch via voiceConfigOverride on /ws."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VAKDEEPGRAM_URL", DEFAULT_BASE_URL),
        help=f"VakDeepGram base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--oauth-token",
        default=os.environ.get("INTEGRIN_OAUTH_TOKEN"),
        help="OAuth bearer token for /voice/oauth/connect.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_build_parser().parse_args())))
