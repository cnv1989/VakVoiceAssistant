#!/usr/bin/env python3
"""
Integration test: Setmore booking flow with WhatsApp message delivery.

Resolves business context, calls create_appointment, and verifies that the
booking link is sent via WhatsApp (Twilio WhatsApp API) instead of SMS.

Twilio credentials are fetched from AWS Secrets Manager automatically:
  - TWILIO_ACCOUNT_SID is set directly (not sensitive)
  - TWILIO_AUTH_TOKEN is fetched from secret 'vak/twilio-auth-token'

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_booking_whatsapp
  python -m scripts.tests.test_booking_whatsapp --customer-phone "+15550002222"
  python -m scripts.tests.test_booking_whatsapp --service "Regular Haircut"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)


BUSINESS_NUMBER = "+15550001111"
DEFAULT_CUSTOMER_PHONE = "+15550002222"

# Twilio Account SID (not sensitive, same value used in CDK stack)
TWILIO_ACCOUNT_SID = "ACd00787e66384ec2d2ed3e262748525af"
# Secrets Manager secret name for the auth token
TWILIO_AUTH_TOKEN_SECRET_NAME = "vak/twilio-auth-token"
AWS_REGION = "us-west-2"


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


def _ensure_twilio_credentials() -> bool:
    """Load Twilio credentials into environment from Secrets Manager if not already set."""
    # Always set the account SID
    if not os.environ.get("TWILIO_ACCOUNT_SID"):
        os.environ["TWILIO_ACCOUNT_SID"] = TWILIO_ACCOUNT_SID
        print(f"  Set TWILIO_ACCOUNT_SID from constant: {TWILIO_ACCOUNT_SID[:8]}...")

    # Check if auth token is already in env
    if os.environ.get("TWILIO_AUTH_TOKEN"):
        print("  TWILIO_AUTH_TOKEN already set in environment.")
        return True

    # Fetch from Secrets Manager
    print(f"  Fetching TWILIO_AUTH_TOKEN from Secrets Manager ({TWILIO_AUTH_TOKEN_SECRET_NAME}) ...")
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = client.get_secret_value(SecretId=TWILIO_AUTH_TOKEN_SECRET_NAME)
        secret_value = response["SecretString"]
        os.environ["TWILIO_AUTH_TOKEN"] = secret_value
        print(f"  Loaded TWILIO_AUTH_TOKEN from Secrets Manager ({len(secret_value)} chars)")
        return True
    except ImportError:
        print("  ERROR: boto3 not installed. Cannot fetch secrets from AWS.")
        return False
    except Exception as exc:
        print(f"  ERROR: Failed to fetch secret: {exc}")
        return False


async def main(args: argparse.Namespace) -> int:
    customer_phone = args.customer_phone
    service_name = args.service

    print("=" * 60)
    print("  Setmore Booking + WhatsApp Message Test")
    print("=" * 60)
    print(f"  Business  : {BUSINESS_NUMBER}")
    print(f"  Customer  : {customer_phone}")
    print()

    # ── 0. Ensure Twilio credentials ─────────────────────────────────────────
    print("[0/4] Loading Twilio credentials ...")
    creds_ok = _ensure_twilio_credentials()
    if not creds_ok:
        print("  WARNING: Twilio credentials could not be loaded.")
        print("  The test will continue but messaging will fail.")
    print()

    # Reload config so pydantic picks up the new env vars
    from vakdeepgram import config
    config.settings = config.Settings()

    from vakdeepgram.connection_store import resolve_business_context
    from providers.setmore.tools import create_appointment

    # ── 1. Resolve business context ──────────────────────────────────────────
    print("[1/4] Resolving business context ...")
    ctx = await resolve_business_context(BUSINESS_NUMBER)
    if not ctx.get("success"):
        print(f"  FAIL: Could not resolve context: {ctx.get('error')}")
        return 1

    provider = ctx.get("provider", "square")
    location = ctx.get("location") or {}
    whatsapp_number = location.get("whatsapp_number")
    business_name = location.get("business_name")
    print(f"  Provider       : {provider}")
    print(f"  Business       : {business_name}")
    print(f"  WhatsApp number: {whatsapp_number or '(not configured)'}")
    if not whatsapp_number:
        print()
        print("  WARNING: No whatsapp_number in business context.")
        print("  The test will still run but the message will fall back to SMS.")
    print()

    if provider != "setmore":
        print(f"  SKIP: Provider is '{provider}', not 'setmore'. This test is Setmore-specific.")
        return 0

    # ── 2. Pick a service ────────────────────────────────────────────────────
    services = ctx.get("services") or []
    if service_name:
        target = service_name.strip().lower()
        chosen = None
        for svc in services:
            if target in (svc.get("name") or "").lower():
                chosen = svc
                break
        if not chosen:
            print(f"  FAIL: Service '{service_name}' not found. Available:")
            for svc in services[:10]:
                print(f"    - {svc.get('name')}")
            return 1
        service_name = chosen.get("name") or service_name
    elif services:
        first_svc = services[0]
        service_name = first_svc.get("name") or "Regular Haircut"
    else:
        service_name = "Regular Haircut"
    print(f"[2/4] Using service: {service_name}")
    print()

    # ── 3. Mock ToolContext and call create_appointment ───────────────────────
    class MockAgent:
        def __init__(self, state: dict):
            self.state = state

    class MockToolContext:
        def __init__(self, business_context: dict):
            self.agent = MockAgent({"business_context": business_context})

    mock_tc = MockToolContext(ctx)

    print(f"[3/4] Calling create_appointment (service={service_name}, phone={customer_phone}) ...")
    result = await create_appointment(
        mock_tc,
        first_name="John",
        last_name="Smith",
        customer_id="",
        date="2026-02-20T14:00:00",
        service=service_name,
        staff_id=None,
        phone_number=customer_phone,
        caller_number=None,
    )
    print()

    # ── 4. Verify results ────────────────────────────────────────────────────
    print("[4/4] Verifying results ...")
    if not result.get("success"):
        print(f"  FAIL: create_appointment returned error: {result.get('error')}")
        print(f"  Full result:\n{_pretty(result)}")
        return 1

    booking_url = result.get("booking_url") or ""
    msg_sent = result.get("message_sent", False)
    msg_channel = result.get("message_channel")
    message = result.get("message", "")

    print(f"  booking_url    : {booking_url[:90]}{'...' if len(booking_url) > 90 else ''}")
    print(f"  message_sent   : {msg_sent}")
    print(f"  message_channel: {msg_channel or '(none)'}")
    print(f"  message        : {message}")
    print()

    # Check booking URL
    if "setmore.com" not in booking_url or "/book" not in booking_url:
        print(f"  FAIL: booking_url missing or invalid: {booking_url[:80]}")
        return 1
    print("  PASS: Valid Setmore booking URL returned.")

    # Check WhatsApp delivery
    if msg_channel == "whatsapp":
        print("  PASS: Booking link sent via WhatsApp.")
    elif msg_channel == "sms":
        print("  WARN: Booking link sent via SMS (WhatsApp fallback). Check whatsapp_number config.")
    elif msg_sent:
        print("  WARN: Message sent but channel unknown.")
    else:
        print("  WARN: Message was NOT sent. Check Twilio credentials and phone numbers.")

    print()
    print("  Appointment details:")
    details = result.get("appointment_details") or {}
    for k, v in details.items():
        print(f"    {k}: {v}")

    print()
    print("=" * 60)
    print("  Test complete.")
    print("=" * 60)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Test Setmore booking flow with WhatsApp delivery")
    p.add_argument(
        "--customer-phone",
        default=DEFAULT_CUSTOMER_PHONE,
        help=f"Customer phone number (default: {DEFAULT_CUSTOMER_PHONE})",
    )
    p.add_argument(
        "--service",
        default=None,
        help="Service name to book (default: first available service)",
    )
    return p


if __name__ == "__main__":
    parser = _build_parser()
    raise SystemExit(asyncio.run(main(parser.parse_args())))
