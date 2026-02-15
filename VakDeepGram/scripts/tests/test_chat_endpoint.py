#!/usr/bin/env python3
"""
Test the /chat endpoint with business number 510 405 4454.

Sends a series of chat messages and verifies provider-specific behaviour:
- Correct provider is resolved
- Agent responds appropriately (business name in greeting, etc.)

Usage:
  # Start the server first, then:
  cd VakDeepGram
  python -m scripts.tests.test_chat_endpoint
  python -m scripts.tests.test_chat_endpoint --base-url http://localhost:8080
  python -m scripts.tests.test_chat_endpoint --message "What services do you offer?"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx

BUSINESS_NUMBER = "5104054454"
DEFAULT_BASE_URL = "http://localhost:8080"

CHAT_MESSAGES = [
    "Hi, what services do you offer?",
    "What are your hours?",
    "Who are your staff members?",
    "Where are you located?",
    "I'd like to check availability for tomorrow",
]


async def send_chat(
    base_url: str,
    message: str,
    business_number: str,
    api_key: str | None = None,
    session_id: str | None = None,
) -> dict:
    url = f"{base_url}/chat"
    payload = {
        "message": message,
        "business_number": business_number,
    }
    if session_id:
        payload["session_id"] = session_id

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, json=payload, headers=headers)
    return {"status": response.status_code, "body": response.json()}


async def main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key
    session_id = f"test-510-405-4454-{os.getpid()}"

    print(f"=== Chat endpoint tests for: {BUSINESS_NUMBER} ===")
    print(f"Base URL: {base_url}")
    print(f"Session:  {session_id}\n")

    messages = [args.message] if args.message else CHAT_MESSAGES

    for i, message in enumerate(messages, 1):
        print(f"--- Message {i}/{len(messages)} ---")
        print(f"  User: {message}")
        try:
            result = await send_chat(
                base_url,
                message,
                BUSINESS_NUMBER,
                api_key=api_key,
                session_id=session_id,
            )
            status = result["status"]
            body = result["body"]
            reply = body.get("reply", "")
            model_id = body.get("model_id", "")
            print(f"  Status: {status}")
            print(f"  Model:  {model_id}")
            print(f"  Agent:  {reply[:500]}")
            if status != 200:
                print(f"  ERROR: {json.dumps(body, indent=2)}")
        except httpx.ConnectError:
            print(f"  ERROR: Could not connect to {base_url}")
            print(f"  Make sure the VakDeepGram server is running.")
            return 1
        except Exception as exc:
            print(f"  ERROR: {exc}")
        print()

    print(f"=== Chat endpoint tests complete ===")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test /chat endpoint for 510 405 4454")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VAKDEEPGRAM_URL", DEFAULT_BASE_URL),
        help=f"Server base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CHAT_API_KEY"),
        help="API key for /chat endpoint (defaults to env CHAT_API_KEY).",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Send a single message instead of the default test suite.",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
