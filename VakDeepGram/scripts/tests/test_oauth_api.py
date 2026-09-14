#!/usr/bin/env python3
"""
Manual OAuth API smoke test for Integrin endpoints.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_oauth_api --base-url http://localhost:8080 \
    --token "$INTEGRIN_OAUTH_TOKEN" --business-number +15550001111
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)


async def main(args: argparse.Namespace) -> int:
    headers = {"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}
    base_url = args.base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=60) as client:
        voice_payload = {
            "business_number": args.business_number,
            "customer_number": args.customer_number,
        }
        voice_resp = await client.post(f"{base_url}/voice/oauth/connect", json=voice_payload, headers=headers)
        print("voice/oauth/connect:", voice_resp.status_code)
        print(voice_resp.text[:1200])

        chat_payload = {
            "message": args.message,
            "business_number": args.business_number,
            "customer_number": args.customer_number,
            "session_id": "oauth-chat-smoke",
        }
        chat_resp = await client.post(f"{base_url}/chat/oauth", json=chat_payload, headers=headers)
        print("\nchat/oauth:", chat_resp.status_code)
        print(chat_resp.text[:1200])

    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OAuth endpoint smoke test")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--token", required=True, help="OAuth bearer token from Integrin app")
    parser.add_argument("--business-number", required=True)
    parser.add_argument("--customer-number", default="+15105550000")
    parser.add_argument("--message", default="Hi, what services do you offer?")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_parser().parse_args())))

