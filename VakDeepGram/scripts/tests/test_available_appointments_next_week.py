#!/usr/bin/env python3
"""
Test script: Fetch available appointment slots for the next week.

Resolves business context for +15104054454 (Mission Barber / Setmore), then
calls the Setmore slots API for each day of the next 7 days and prints
available times per day.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_available_appointments_next_week
  python -m scripts.tests.test_available_appointments_next_week --service "Haircut"
  python -m scripts.tests.test_available_appointments_next_week --days 14
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

BUSINESS_NUMBER = "+15104054454"
DEFAULT_DAYS = 7


async def main(args: argparse.Namespace) -> int:
    from vakdeepgram.connection_store import resolve_business_context
    from providers.clients import SetmoreApiClient, ensure_provider_access_context
    from providers.setmore.helpers import format_date, slot_to_iso

    service_name = (args.service or "").strip()
    days = max(1, args.days)

    print("=" * 70)
    print("  Available Appointments — Next Week")
    print("=" * 70)
    print(f"  Business : {BUSINESS_NUMBER}")
    print(f"  Days     : {days}")
    print()

    # Resolve context
    print("Resolving business context ...")
    ctx = await resolve_business_context(BUSINESS_NUMBER)
    if not ctx.get("success"):
        print(f"FAIL: Could not resolve context: {ctx.get('error')}")
        return 1

    provider = ctx.get("provider", "square")
    if provider != "setmore":
        print(f"SKIP: Provider is '{provider}'. This script is for Setmore businesses.")
        return 0

    location = ctx.get("location") or {}
    timezone_name = location.get("timezone") or "America/Los_Angeles"
    business_name = location.get("business_name") or "Business"
    print(f"  Provider : {provider}")
    print(f"  Business : {business_name}")
    print(f"  Timezone : {timezone_name}")
    print()

    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(timezone_name)
    except Exception:
        tzinfo = None

    auth = await ensure_provider_access_context(business_context=ctx)
    if not auth.get("success"):
        print(f"FAIL: Unable to resolve Setmore auth: {auth.get('error')}")
        return 1
    setmore_client = SetmoreApiClient(
        auth["access_token"],
        refresh_token=auth.get("refresh_token"),
    )

    # Pick service
    services = ctx.get("services") or []
    if not services:
        print("FAIL: No services in context.")
        return 1

    service_item = None
    if service_name:
        target = service_name.lower()
        for svc in services:
            if target in (svc.get("name") or "").lower():
                service_item = svc
                break
        if not service_item:
            print(f"FAIL: Service '{service_name}' not found. Available: {[s.get('name') for s in services[:10]]}")
            return 1
    else:
        service_item = services[0]

    service_key = service_item.get("id")
    service_display = service_item.get("name") or "Service"
    if not service_key:
        print("FAIL: Service has no id.")
        return 1

    # Pick staff (first available)
    staff_list = ctx.get("staff") or []
    if not staff_list:
        print("FAIL: No staff in context.")
        return 1
    staff_item = staff_list[0]
    staff_key = staff_item.get("id")
    staff_display = f"{staff_item.get('first_name', '')} {staff_item.get('last_name', '')}".strip() or staff_key
    if not staff_key:
        print("FAIL: Staff has no id.")
        return 1

    print(f"  Service : {service_display} ({service_key[:8]}...)")
    print(f"  Staff   : {staff_display} ({staff_key[:8]}...)")
    print()

    # Fetch slots for each day
    today = datetime.now(tz=tzinfo) if tzinfo else datetime.now()
    payload_base = {
        "service_key": service_key,
        "staff_key": staff_key,
        "timezone": timezone_name,
    }
    print("-" * 70)
    print(f"  {'Date':<12}  {'Day':<10}  Slots")
    print("-" * 70)

    total_slots = 0
    days_with_slots = 0
    for day_offset in range(days):
        day_date = today + timedelta(days=day_offset)
        selected_date = format_date(day_date)
        payload = {**payload_base, "selected_date": selected_date}
        result = await setmore_client.fetch_slots(payload)
        if not result.get("success"):
            day_name = day_date.strftime("%A")
            date_str = day_date.strftime("%Y-%m-%d")
            print(f"  {date_str}  {day_name:<10}  ERR  {result.get('error')}")
            continue
        slots_raw = result.get("slots") or []
        slots_iso = []
        for slot_str in slots_raw:
            iso_val = slot_to_iso(day_date.replace(hour=0, minute=0, second=0, microsecond=0), slot_str, tzinfo)
            if iso_val:
                time_part = iso_val.split("T")[-1][:5]
                slots_iso.append(time_part)
        slots_iso.sort()
        count = len(slots_iso)
        if count:
            total_slots += count
            days_with_slots += 1
        day_name = day_date.strftime("%A")
        date_str = day_date.strftime("%Y-%m-%d")
        if count == 0:
            slot_summary = "(none)"
        elif count <= 8:
            slot_summary = ", ".join(slots_iso)
        else:
            slot_summary = ", ".join(slots_iso[:6]) + f" ... +{count - 6} more"
        print(f"  {date_str}  {day_name:<10}  {count:>3}  {slot_summary}")

    print("-" * 70)
    print(f"  Total: {total_slots} slots over {days_with_slots} days (next {days} days)")
    print("=" * 70)
    if total_slots == 0:
        print("FAIL: Expected available slots over next week, but found none.")
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check available appointment slots for the next week")
    p.add_argument("--service", default=None, help="Service name (default: first service)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Number of days to check (default: {DEFAULT_DAYS})")
    return p


if __name__ == "__main__":
    parser = _build_parser()
    raise SystemExit(asyncio.run(main(parser.parse_args())))
