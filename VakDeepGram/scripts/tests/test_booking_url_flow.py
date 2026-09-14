#!/usr/bin/env python3
"""
E2E test: Setmore booking URL flow via the /chat API.

Sends a short conversation that should lead to create_appointment returning
a prefilled booking link. Asserts that the agent response contains a
Setmore booking URL (e.g. ...setmore.com/book?...).

This test can fail with "No Setmore booking URL" if the business has no
available slots on the requested dates (check_availability returns empty).
The booking URL logic is still verified by:
  - scripts.tests.test_booking_url_builder  (unit test: URL building)
  - scripts.tests.test_booking_url_tool     (integration: create_appointment with real context)

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_booking_url_flow
  python -m scripts.tests.test_booking_url_flow --base-url http://localhost:8080
  python -m scripts.tests.test_booking_url_flow --timeout 120 --request-timeout 60
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

import httpx

BUSINESS_NUMBER = "+15550001111"
CUSTOMER_NUMBER = "+15550002222"
DEFAULT_BASE_URL = "http://localhost:8080"
# Total test timeout (all messages). Single request still limited by httpx timeout.
DEFAULT_TEST_TIMEOUT_SEC = 300  # 5 min

# Conversation aimed at reaching the booking URL.
# Use Tuesday 17 Feb (known to return slots from Setmore API).
# Start with a services question so the agent has context, then book.
BOOKING_MESSAGES = [
    "What services do you offer?",
    "I'd like to book the Haircut and Wet Shave for next Tuesday at 2 PM.",
    "Any barber is fine. My name is John Smith, phone +1 510 579 6565.",
    "Yes, that's correct.",
]


def extract_urls(text: str) -> list[str]:
    """Return URLs found in text (simple http/https)."""
    return re.findall(r"https?://[^\s\)\]\"']+", text)


def is_booking_url(url: str) -> bool:
    """True if URL looks like a Setmore booking page."""
    return "setmore.com" in url.lower() and "/book" in url


async def run(
    base_url: str,
    business_number: str,
    customer_number: str,
    session_id: str,
    request_timeout: float = 90,
) -> tuple[bool, list[str], list[str]]:
    """Send booking messages; return (found_booking_url, all_replies, all_urls)."""
    url = f"{base_url}/chat"
    all_replies: list[str] = []
    all_urls: list[str] = []

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        for i, message in enumerate(BOOKING_MESSAGES):
            payload = {
                "message": message,
                "business_number": business_number,
                "customer_number": customer_number,
                "session_id": session_id,
            }
            print(f"  User: {message}")
            t0 = time.monotonic()
            try:
                r = await client.post(url, json=payload)
            except httpx.ConnectError:
                print(f"  ERROR: Cannot connect to {base_url}")
                return False, all_replies, all_urls
            elapsed = (time.monotonic() - t0) * 1000
            if r.status_code != 200:
                print(f"  ERROR: {r.status_code} {r.text[:200]}")
                all_replies.append("")
                continue
            body = r.json()
            reply = body.get("reply", "")
            all_replies.append(reply)
            urls = extract_urls(reply)
            all_urls.extend(urls)
            # Show first line of reply
            first_line = reply.split("\n")[0][:80]
            print(f"  Agent ({int(elapsed)} ms): {first_line}...")
            if any(is_booking_url(u) for u in urls):
                print(f"  >>> Booking URL found: {[u for u in urls if is_booking_url(u)][0][:70]}...")
                return True, all_replies, all_urls
            print()

    return False, all_replies, all_urls


async def main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    session_id = args.session_id or f"booking-url-test-{os.getpid()}"

    print("=" * 60)
    print("  Setmore booking URL flow test")
    print("=" * 60)
    print(f"  Server   : {base_url}")
    print(f"  Business : {args.business_number}")
    print(f"  Customer : {args.customer_number}")
    print(f"  Session  : {session_id}")
    print(f"  Timeout  : {args.timeout}s total, {args.request_timeout}s per request")
    print("=" * 60)
    print()

    try:
        found, replies, urls = await asyncio.wait_for(
            run(
                base_url,
                args.business_number,
                args.customer_number,
                session_id,
                request_timeout=args.request_timeout,
            ),
            timeout=args.timeout,
        )
    except asyncio.TimeoutError:
        print(f"\nFAIL: Test timed out after {args.timeout}s.")
        return 1

    print()
    if found:
        print("PASS: Agent returned a Setmore booking URL.")
        return 0
    print("FAIL: No Setmore booking URL in agent replies.")
    if urls:
        print(f"  URLs seen: {urls}")
    if replies:
        print("  Last reply (full):")
        for line in replies[-1].split("\n"):
            print(f"    {line}")
    return 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Test Setmore booking URL flow via /chat")
    p.add_argument("--base-url", default=os.environ.get("VAKDEEPGRAM_URL", DEFAULT_BASE_URL))
    p.add_argument("--business-number", default=BUSINESS_NUMBER)
    p.add_argument("--customer-number", default=CUSTOMER_NUMBER)
    p.add_argument("--session-id", default=None)
    p.add_argument("--timeout", type=float, default=DEFAULT_TEST_TIMEOUT_SEC, help="Total test timeout (seconds)")
    p.add_argument("--request-timeout", type=float, default=90, help="Per-request HTTP timeout (seconds)")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_build_parser().parse_args())))
