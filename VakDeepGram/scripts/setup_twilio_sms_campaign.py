#!/usr/bin/env python3
"""
Create Twilio resources for an A2P 10DLC SMS campaign (Sole Proprietor).

This script:
  1. Creates a Messaging Service (for use when you register the Campaign in Console).
  2. Optionally searches for and buys a US 10DLC (Local) number and adds it to the service.

You must still complete in Twilio Console (cannot be automated):
  - Create Starter Profile (no business Tax ID → Sole Proprietor).
  - Register Brand (OTP sent to your mobile).
  - Register Campaign and link it to the Messaging Service created here.

Usage:
  Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env or environment, then:
    python scripts/setup_twilio_sms_campaign.py
    python scripts/setup_twilio_sms_campaign.py --no-buy-number   # only create the service

Console: https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-onboarding
"""

from __future__ import annotations

import argparse
import os
import sys

# Load .env from project root (VakDeepGram)
try:
    import dotenv
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dotenv.load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass

try:
    from twilio.rest import Client
except ImportError:
    print("twilio package required. From VakDeepGram: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


MESSAGING_SERVICE_FRIENDLY_NAME = "A2P 10DLC Sole Proprietor"


def get_client():
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print(
            "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    return Client(account_sid, auth_token)


def create_messaging_service(client: Client) -> str:
    """Create a Messaging Service; return its SID."""
    service = client.messaging.v1.services.create(
        friendly_name=MESSAGING_SERVICE_FRIENDLY_NAME,
    )
    print(f"Created Messaging Service: {service.sid} ({service.friendly_name})")
    return service.sid


def search_local_numbers(client: Client, area_code: str | None = None) -> list[str]:
    """Search for available US Local (10DLC) numbers. Returns list of phone numbers."""
    kwargs = {"in_region": "US", "sms_enabled": True}
    if area_code:
        kwargs["area_code"] = area_code
    results = client.available_phone_numbers("US").local.list(**kwargs)
    return [n.phone_number for n in results[:10]]


def buy_number(client: Client, phone_number: str) -> str:
    """Purchase the given phone number; return SID of the new IncomingPhoneNumber."""
    number = client.incoming_phone_numbers.create(phone_number=phone_number)
    print(f"Purchased number: {number.phone_number} (SID: {number.sid})")
    return number.sid


def add_sender_to_service(
    client: Client, service_sid: str, phone_number_sid: str
) -> None:
    """Add a phone number (by its SID) to the Messaging Service's Sender Pool."""
    client.messaging.v1.services(service_sid).phone_numbers.create(
        phone_number_sid=phone_number_sid
    )
    print(f"Added phone number {phone_number_sid} to Messaging Service {service_sid}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Twilio Messaging Service and optionally buy a 10DLC number for A2P campaign."
    )
    parser.add_argument(
        "--no-buy-number",
        action="store_true",
        help="Only create the Messaging Service; do not search/buy a number.",
    )
    parser.add_argument(
        "--area-code",
        type=str,
        default=None,
        help="US area code for number search (e.g. 415).",
    )
    args = parser.parse_args()

    client = get_client()

    service_sid = create_messaging_service(client)

    if args.no_buy_number:
        print("\nSkipping number purchase (--no-buy-number).")
        print("Add a 10DLC number later: Console → Messaging → Services →", MESSAGING_SERVICE_FRIENDLY_NAME)
    else:
        print("\nSearching for US Local (10DLC) numbers...")
        numbers = search_local_numbers(client, args.area_code)
        if not numbers:
            print("No available numbers found. Try another area code with --area-code 415", file=sys.stderr)
            sys.exit(1)
        first = numbers[0]
        number_sid = buy_number(client, first)
        add_sender_to_service(client, service_sid, number_sid)
        print(f"\nNumber to use for A2P: {first}")

    print("\nNext steps (in Twilio Console):")
    print("  1. Open: https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-onboarding")
    print("  2. Create Starter Profile (no Tax ID → Sole Proprietor).")
    print("  3. Register Brand; complete OTP on your mobile.")
    print("  4. Register Campaign → choose 'Select existing Messaging Service' and pick:")
    print(f"     {MESSAGING_SERVICE_FRIENDLY_NAME} ({service_sid})")
    print("  5. After campaign is VERIFIED, send SMS via this Messaging Service SID in your app.")
    print(f"\nMessaging Service SID: {service_sid}")


if __name__ == "__main__":
    main()
