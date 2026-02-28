#!/usr/bin/env python3
"""
Call Setmore slots API and print the raw response.

Use this to verify the API returns slots and to see the exact response
structure (in case _extract_list is missing the list).

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_slots_raw
  python -m scripts.tests.test_setmore_slots_raw --date 20/02/2026
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

import httpx
from vakdeepgram import config
from vakdeepgram.connection_store import resolve_business_context
from providers.clients import ensure_provider_access_context

BUSINESS_NUMBER = "+15104054454"


async def main(selected_date_override: str | None = None) -> int:
    print("Resolving business context ...")
    ctx = await resolve_business_context(BUSINESS_NUMBER)
    if not ctx.get("success"):
        print(f"FAIL: {ctx.get('error')}")
        return 1
    if ctx.get("provider") != "setmore":
        print(f"Provider is {ctx.get('provider')}, not setmore. Skip.")
        return 0

    auth = await ensure_provider_access_context(business_context=ctx)
    if not auth.get("success") or not auth.get("access_token"):
        print(f"FAIL: Could not resolve Setmore auth token: {auth.get('error')}")
        return 1
    token = auth["access_token"]

    services = ctx.get("services") or []
    staff = ctx.get("staff") or []
    if not services or not staff:
        print("FAIL: No services or staff in context")
        return 1

    service_key = services[0].get("id")
    staff_key = staff[0].get("id")
    service_name = services[0].get("name", "?")
    staff_name = f"{staff[0].get('first_name', '')} {staff[0].get('last_name', '')}".strip()

    # Date: default tomorrow in DD/MM/YYYY (same as test_setmore_apis)
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    selected_date = selected_date_override or tomorrow

    location = ctx.get("location") or {}
    timezone_name = location.get("timezone")

    payload = {
        "staff_key": staff_key,
        "service_key": service_key,
        "selected_date": selected_date,
    }
    if timezone_name:
        payload["timezone"] = timezone_name

    url = f"{config.settings.setmore_api_base_url.rstrip('/')}/bookingapi/slots"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print(f"\nRequest:")
    print(f"  URL: {url}")
    print(f"  Service: {service_name} (key={service_key})")
    print(f"  Staff: {staff_name} (key={staff_key})")
    print(f"  selected_date: {selected_date}")
    print(f"  timezone: {timezone_name}")
    print(f"  Body: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)

    print(f"\nResponse:")
    print(f"  Status: {response.status_code}")
    try:
        body = response.json()
        print(f"  Body (raw):")
        print(json.dumps(body, indent=2, default=str))
        data = body.get("data")
        if data is not None:
            slots_list = None
            if isinstance(data, list):
                slots_list = data
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list):
                        slots_list = v
                        print(f"\n  Extracted list from data.{k}: len={len(v)}")
                        break
            if slots_list:
                print(f"  Slots ({len(slots_list)}):")
                for s in slots_list[:20]:
                    print(f"    - {s}")
                if len(slots_list) > 20:
                    print(f"    ... and {len(slots_list) - 20} more")
            else:
                print("  No list found in data.")
    except Exception as e:
        print(f"  Text: {response.text[:500]}")
        print(f"  Parse error: {e}")

    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="Date DD/MM/YYYY (default: tomorrow)")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.date)))
