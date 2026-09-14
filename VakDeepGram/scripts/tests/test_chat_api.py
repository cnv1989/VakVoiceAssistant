#!/usr/bin/env python3
"""
Test the /chat API on localhost for a specific business and customer number.

Business Number : +15550001111
Customer Number : +15550002222

Modes:
  - Default (no flags): sends a preset sequence of messages.
  - Interactive (--interactive / -i): opens a REPL so you can chat freely.
  - Single message (--message "..."): sends one message and exits.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_chat_api
  python -m scripts.tests.test_chat_api -i
  python -m scripts.tests.test_chat_api --message "What services do you offer?"
  python -m scripts.tests.test_chat_api --base-url http://localhost:8080
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

import httpx

# ── Defaults ──────────────────────────────────────────────────────────────────
BUSINESS_NUMBER = "+15550001111"
CUSTOMER_NUMBER = "+15550002222"
DEFAULT_BASE_URL = "http://localhost:8080"

# Preset conversation for the automated run
PRESET_MESSAGES = [
    "Hi there!",
    "What services do you offer?",
    "What are your business hours?",
    "Where are you located? What is your address?",
    "Who are the staff members?",
    "I'd like to book an appointment for a haircut tomorrow afternoon",
    "What is the phone number for the store?",
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────
async def send_chat(
    client: httpx.AsyncClient,
    base_url: str,
    message: str,
    business_number: str,
    customer_number: str | None = None,
    session_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Post a single message to /chat and return the parsed response."""
    url = f"{base_url}/chat"
    payload: dict[str, str] = {
        "message": message,
        "business_number": business_number,
    }
    if customer_number:
        payload["customer_number"] = customer_number
    if session_id:
        payload["session_id"] = session_id

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.monotonic()
    response = await client.post(url, json=payload, headers=headers)
    elapsed_ms = (time.monotonic() - t0) * 1000

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    return {
        "status": response.status_code,
        "elapsed_ms": round(elapsed_ms),
        "body": body,
    }


def _print_result(result: dict, index: int | None = None) -> None:
    """Pretty-print a single chat result."""
    status = result["status"]
    elapsed = result["elapsed_ms"]
    body = result["body"]
    reply = body.get("reply", "")
    model_id = body.get("model_id", "")

    prefix = f"[{index}] " if index is not None else ""
    print(f"  {prefix}Status : {status}  ({elapsed} ms)")
    if model_id:
        print(f"  {prefix}Model  : {model_id}")
    if status == 200:
        print(f"  {prefix}Agent  : {reply}")
    else:
        print(f"  {prefix}ERROR  : {json.dumps(body, indent=2)}")


# ── Run modes ─────────────────────────────────────────────────────────────────
async def run_preset(
    base_url: str,
    business_number: str,
    customer_number: str,
    session_id: str,
    api_key: str | None,
) -> int:
    """Send the preset message sequence."""
    print(f"Sending {len(PRESET_MESSAGES)} preset messages ...\n")
    async with httpx.AsyncClient(timeout=120) as client:
        for i, message in enumerate(PRESET_MESSAGES, 1):
            print(f"--- [{i}/{len(PRESET_MESSAGES)}] User: {message}")
            try:
                result = await send_chat(
                    client,
                    base_url,
                    message,
                    business_number,
                    customer_number=customer_number,
                    session_id=session_id,
                    api_key=api_key,
                )
                _print_result(result, index=i)
            except httpx.ConnectError:
                print(f"  ERROR: Could not connect to {base_url}")
                print("  Make sure the VakDeepGram server is running.")
                return 1
            except Exception as exc:
                print(f"  ERROR: {exc}")
            print()
    return 0


async def run_single(
    base_url: str,
    message: str,
    business_number: str,
    customer_number: str,
    session_id: str,
    api_key: str | None,
) -> int:
    """Send a single message."""
    print(f"User: {message}\n")
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            result = await send_chat(
                client,
                base_url,
                message,
                business_number,
                customer_number=customer_number,
                session_id=session_id,
                api_key=api_key,
            )
            _print_result(result)
        except httpx.ConnectError:
            print(f"  ERROR: Could not connect to {base_url}")
            return 1
        except Exception as exc:
            print(f"  ERROR: {exc}")
            return 1
    return 0


async def run_interactive(
    base_url: str,
    business_number: str,
    customer_number: str,
    session_id: str,
    api_key: str | None,
) -> int:
    """Interactive REPL — type messages, get responses."""
    print("Interactive mode — type your messages (Ctrl-C or 'quit' to exit).\n")
    async with httpx.AsyncClient(timeout=120) as client:
        turn = 0
        while True:
            try:
                message = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                break
            if not message:
                continue
            if message.lower() in ("quit", "exit", "q"):
                print("Bye!")
                break

            turn += 1
            try:
                result = await send_chat(
                    client,
                    base_url,
                    message,
                    business_number,
                    customer_number=customer_number,
                    session_id=session_id,
                    api_key=api_key,
                )
                _print_result(result)
            except httpx.ConnectError:
                print(f"  ERROR: Could not connect to {base_url}")
                return 1
            except Exception as exc:
                print(f"  ERROR: {exc}")
            print()
    return 0


# ── Entrypoint ────────────────────────────────────────────────────────────────
async def main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key
    business_number = args.business_number
    customer_number = args.customer_number
    session_id = args.session_id or f"test-chat-{business_number}-{os.getpid()}"

    print("=" * 60)
    print("  VakDeepGram /chat API Test")
    print("=" * 60)
    print(f"  Server   : {base_url}")
    print(f"  Business : {business_number}")
    print(f"  Customer : {customer_number}")
    print(f"  Session  : {session_id}")
    print(f"  Auth     : {'API key set' if api_key else 'none (dev mode)'}")
    print("=" * 60)
    print()

    if args.interactive:
        return await run_interactive(base_url, business_number, customer_number, session_id, api_key)
    elif args.message:
        return await run_single(base_url, args.message, business_number, customer_number, session_id, api_key)
    else:
        return await run_preset(base_url, business_number, customer_number, session_id, api_key)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test /chat API on localhost for business +15550001111",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VAKDEEPGRAM_URL", DEFAULT_BASE_URL),
        help=f"Server base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--business-number",
        default=BUSINESS_NUMBER,
        help=f"Business phone number (default: {BUSINESS_NUMBER}).",
    )
    parser.add_argument(
        "--customer-number",
        default=CUSTOMER_NUMBER,
        help=f"Customer phone number (default: {CUSTOMER_NUMBER}).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CHAT_API_KEY"),
        help="API key for /chat endpoint (defaults to env CHAT_API_KEY).",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Custom session ID (default: auto-generated).",
    )
    parser.add_argument(
        "-m", "--message",
        default=None,
        help="Send a single message instead of the preset sequence.",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Interactive REPL mode — type messages freely.",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
