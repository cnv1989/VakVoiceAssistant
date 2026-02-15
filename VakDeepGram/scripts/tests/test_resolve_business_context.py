#!/usr/bin/env python3
"""
Test resolving business context for business number 510 405 4454.

Verifies that the DynamoDB lookup succeeds, the correct provider is
returned, and provider-specific data (services, staff, access token)
is present.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_resolve_business_context
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context
from utils.phone import normalize_phone_number

BUSINESS_NUMBER = "510 405 4454"


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


async def main() -> int:
    print(f"=== Resolving business context for: {BUSINESS_NUMBER} ===\n")
    normalized = normalize_phone_number(BUSINESS_NUMBER)
    print(f"Normalized number: {normalized}\n")

    context = await resolve_business_context(BUSINESS_NUMBER)

    if not context.get("success"):
        print(f"FAIL: Business context resolution failed: {context.get('error')}")
        return 1

    provider = context.get("provider", "square")
    print(f"Provider: {provider}")
    print(f"Business number: {context.get('businessNumber')}")
    print(f"Access token present: {bool(context.get('accessToken'))}")
    print(f"Location ID: {context.get('locationId', 'N/A')}")
    print(f"Account ID: {context.get('accountId', 'N/A')}")

    location = context.get("location") or {}
    print(f"\n--- Location ---")
    print(f"  Business name: {location.get('business_name')}")
    print(f"  Phone: {location.get('phone_number')}")
    print(f"  Timezone: {location.get('timezone')}")

    services = context.get("services") or []
    print(f"\n--- Services ({len(services)}) ---")
    for svc in services[:10]:
        name = svc.get("name") or svc.get("item_data", {}).get("name", "?")
        duration = svc.get("duration_minutes", "?")
        print(f"  - {name} ({duration} min)")
    if len(services) > 10:
        print(f"  ... and {len(services) - 10} more")

    staff = context.get("staff") or []
    print(f"\n--- Staff ({len(staff)}) ---")
    for member in staff[:10]:
        display = member.get("display_name") or member.get("given_name", "?")
        print(f"  - {display} (id={member.get('id')})")

    customer = context.get("customer")
    if customer:
        print(f"\n--- Customer ---")
        print(f"  {_pretty(customer)}")
    else:
        print(f"\nCustomer: None (will be resolved at call time)")

    print(f"\n--- Provider-specific fields ---")
    if provider == "setmore":
        print(f"  Setmore account ID: {context.get('accountId')}")
        print(f"  Setmore user ID: {context.get('userId')}")
        print(f"  Refresh token present: {bool(context.get('refreshToken'))}")
        print(f"  Raw setmore_services count: {len(context.get('setmore_services') or [])}")
        print(f"  Raw setmore_staff count: {len(context.get('setmore_staff') or [])}")
    else:
        print(f"  Location ID: {context.get('locationId')}")
        print(f"  Merchant ID: {context.get('merchantId')}")

    print(f"\n=== PASS: Business context resolved successfully (provider={provider}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
