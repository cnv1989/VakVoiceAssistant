#!/usr/bin/env python3
"""
End-to-end OAuth smoke test using Cognito user pool credentials.

Needs a real Cognito user pool and a test user in it. Pass the pool details
via --user-pool-id/--client-id (or COGNITO_USER_POOL_ID /
COGNITO_USER_POOL_CLIENT_ID) and prefer the environment for the password.

Usage:
  export COGNITO_USER_POOL_ID=us-west-2_xxxxxxxxx
  export COGNITO_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
  export COGNITO_TEST_USERNAME='you@example.com'
  export COGNITO_TEST_PASSWORD='...'
  python -m scripts.tests.test_cognito_oauth \
    --business-number +15550001111 \
    --base-url http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Dict
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import boto3
import httpx

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)


# No defaults for the pool/client: they identify one specific deployment, so
# they have to come from your own environment or the command line.
DEFAULT_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
DEFAULT_CLIENT_ID = os.environ.get("COGNITO_USER_POOL_CLIENT_ID")
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-west-2")


def get_cognito_tokens(*, region: str, client_id: str, username: str, password: str) -> Dict[str, str]:
    client = boto3.client("cognito-idp", region_name=region)
    response = client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    auth = response.get("AuthenticationResult") or {}
    id_token = auth.get("IdToken")
    access_token = auth.get("AccessToken")
    refresh_token = auth.get("RefreshToken")
    if not id_token or not access_token:
        raise RuntimeError("Cognito did not return IdToken/AccessToken.")
    return {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token or "",
    }


async def exercise_endpoints(
    *,
    base_url: str,
    bearer_token: str,
    business_number: str,
    customer_number: str,
    message: str,
) -> int:
    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
    voice_payload = {
        "business_number": business_number,
        "customer_number": customer_number,
    }
    chat_payload = {
        "message": message,
        "business_number": business_number,
        "customer_number": customer_number,
        "session_id": "cognito-oauth-smoke",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        voice_resp = await client.post(f"{base_url.rstrip('/')}/voice/oauth/connect", headers=headers, json=voice_payload)
        print(f"voice/oauth/connect: {voice_resp.status_code}")
        try:
            voice_body = voice_resp.json()
            ws_url = voice_body.get("websocket_url")
            if isinstance(ws_url, str) and ws_url:
                parsed = urlparse(ws_url)
                params = [(k, ("[REDACTED]" if k == "access_token" else v)) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
                voice_body["websocket_url"] = urlunparse(parsed._replace(query=urlencode(params)))
            print(json.dumps(voice_body)[:1200])
        except Exception:
            print(voice_resp.text[:1200])
        if voice_resp.status_code != 200:
            return 1
        websocket_url = voice_resp.json().get("websocket_url")
        if not websocket_url:
            print("voice/oauth/connect missing websocket_url")
            return 1

        chat_resp = await client.post(f"{base_url.rstrip('/')}/chat/oauth", headers=headers, json=chat_payload)
        print(f"\nchat/oauth: {chat_resp.status_code}")
        print(chat_resp.text[:1200])
        if chat_resp.status_code != 200:
            return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VakDeepGram OAuth E2E with Cognito credentials")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--user-pool-id", default=os.environ.get("COGNITO_USER_POOL_ID", DEFAULT_POOL_ID))
    parser.add_argument("--client-id", default=os.environ.get("COGNITO_USER_POOL_CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--username", default=os.environ.get("COGNITO_TEST_USERNAME"), required=False)
    parser.add_argument("--password", default=os.environ.get("COGNITO_TEST_PASSWORD"), required=False)
    parser.add_argument("--business-number", default="+15550001111")
    parser.add_argument("--customer-number", default="+15105550000")
    parser.add_argument("--message", default="Hi, what services are available this week?")
    parser.add_argument(
        "--token-type",
        choices=["id", "access"],
        default="id",
        help="Which Cognito token to use as bearer token for API calls.",
    )
    parser.add_argument(
        "--print-tokens",
        action="store_true",
        help="Print token payload fields for debugging (never use in shared logs).",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    if not args.username or not args.password:
        raise RuntimeError("Provide --username/--password or COGNITO_TEST_USERNAME/COGNITO_TEST_PASSWORD.")

    tokens = get_cognito_tokens(
        region=args.region,
        client_id=args.client_id,
        username=args.username,
        password=args.password,
    )
    bearer_token = tokens["id_token"] if args.token_type == "id" else tokens["access_token"]
    if args.print_tokens:
        print(json.dumps({"token_type": args.token_type, "token_chars": len(bearer_token)}, indent=2))

    return await exercise_endpoints(
        base_url=args.base_url,
        bearer_token=bearer_token,
        business_number=args.business_number,
        customer_number=args.customer_number,
        message=args.message,
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
