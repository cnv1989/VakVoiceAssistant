#!/usr/bin/env python3
"""
Test Setmore API calls using the resolved context for business number 510 405 4454.

Tests: get_access_token, fetch_services, fetch_staff, fetch_slots,
       fetch_customer, fetch_appointments.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_apis
  python -m scripts.tests.test_setmore_apis --test fetch-services
  python -m scripts.tests.test_setmore_apis --test fetch-slots --service "Haircut"
  python -m scripts.tests.test_setmore_apis --test fetch-customer --first-name "John"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context
from utils import setmore_api

BUSINESS_NUMBER = "510 405 4454"


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


async def _resolve_context() -> dict:
    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        print(f"FAIL: Cannot resolve context: {context.get('error')}")
        sys.exit(1)
    provider = context.get("provider", "square")
    if provider != "setmore":
        print(f"INFO: Provider for {BUSINESS_NUMBER} is '{provider}', not 'setmore'.")
        print("This script is designed for Setmore businesses. Skipping Setmore-specific tests.")
        sys.exit(0)
    return context


async def test_fetch_services(context: dict) -> None:
    print("--- fetch_services ---")
    token = context["accessToken"]
    result = await setmore_api.fetch_services(token)
    print(f"Success: {result.get('success')}")
    services = result.get("services") or []
    print(f"Service count: {len(services)}")
    for svc in services[:10]:
        key = svc.get("key") or svc.get("service_id")
        name = svc.get("service_name") or svc.get("name")
        duration = svc.get("duration")
        print(f"  - {name} (key={key}, duration={duration})")
    if len(services) > 10:
        print(f"  ... and {len(services) - 10} more")
    print()

    # Show normalized services with categories from context
    normalized = context.get("services") or []
    categorized = [s for s in normalized if s.get("category_name")]
    uncategorized = [s for s in normalized if not s.get("category_name")]
    print(f"  Categorized: {len(categorized)}, Uncategorized: {len(uncategorized)}")
    categories_seen: dict[str, list[str]] = {}
    for s in normalized:
        cat = s.get("category_name") or "Uncategorized"
        categories_seen.setdefault(cat, []).append(s.get("name") or "?")
    for cat, names in categories_seen.items():
        print(f"  [{cat}] {', '.join(names)}")
    print()


async def test_fetch_service_categories(context: dict) -> None:
    print("--- fetch_service_categories ---")
    token = context["accessToken"]
    result = await setmore_api.fetch_service_categories(token)
    print(f"Success: {result.get('success')}")
    categories = result.get("service_categories") or []
    print(f"Category count: {len(categories)}")
    for cat in categories:
        key = cat.get("key")
        name = cat.get("category_name")
        service_ids = cat.get("service_id_list") or []
        print(f"  - {name} (key={key}, services={len(service_ids)})")
        for sid in service_ids[:5]:
            print(f"      service_key: {sid}")
        if len(service_ids) > 5:
            print(f"      ... and {len(service_ids) - 5} more")
    print()


async def test_fetch_company(context: dict) -> None:
    print("--- fetch_company ---")
    token = context["accessToken"]
    result = await setmore_api.fetch_company(token)
    print(f"Success: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return
    company = result.get("company") or {}
    for key, value in company.items():
        if value:
            print(f"  {key}: {value}")
    print()


async def test_fetch_staff(context: dict) -> None:
    print("--- fetch_staff ---")
    token = context["accessToken"]
    result = await setmore_api.fetch_staff(token)
    print(f"Success: {result.get('success')}")
    staffs = result.get("staffs") or []
    print(f"Staff count: {len(staffs)}")
    for staff in staffs[:10]:
        key = staff.get("key") or staff.get("staff_id")
        first = staff.get("first_name") or ""
        last = staff.get("last_name") or ""
        print(f"  - {first} {last} (key={key})")
    print()


async def test_fetch_slots(context: dict, service_name: str | None = None) -> None:
    print("--- fetch_slots ---")
    token = context["accessToken"]

    # Resolve service key
    services = context.get("services") or []
    service_item = None
    if service_name:
        target = service_name.strip().lower()
        for svc in services:
            if target in (svc.get("name") or "").lower():
                service_item = svc
                break
    if not service_item and services:
        service_item = services[0]
    if not service_item:
        print("SKIP: No services available to test slots.")
        return

    # Resolve staff key
    staff = context.get("staff") or []
    staff_key = staff[0].get("id") if staff else None
    if not staff_key:
        print("SKIP: No staff available to test slots.")
        return

    service_key = service_item.get("id")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    payload = {
        "staff_key": staff_key,
        "service_key": service_key,
        "selected_date": tomorrow,
    }
    tz = (context.get("location") or {}).get("timezone")
    if tz:
        payload["timezone"] = tz

    print(f"  Service: {service_item.get('name')} (key={service_key})")
    print(f"  Staff: {staff_key}")
    print(f"  Date: {tomorrow}")
    result = await setmore_api.fetch_slots(token, payload)
    print(f"  Success: {result.get('success')}")
    slots = result.get("slots") or []
    print(f"  Slot count: {len(slots)}")
    for slot in slots[:15]:
        print(f"    - {slot}")
    if len(slots) > 15:
        print(f"    ... and {len(slots) - 15} more")
    print()


async def test_fetch_customer(context: dict, first_name: str | None = None) -> None:
    print("--- fetch_customer ---")
    token = context["accessToken"]
    name = first_name or "Test"
    print(f"  Searching for first_name='{name}'")
    result = await setmore_api.fetch_customer(token, first_name=name)
    print(f"  Success: {result.get('success')}")
    customers = result.get("customers") or []
    print(f"  Customer count: {len(customers)}")
    for cust in customers[:5]:
        key = cust.get("key")
        first = cust.get("first_name") or ""
        last = cust.get("last_name") or ""
        phone = cust.get("cell_phone") or ""
        print(f"    - {first} {last} (key={key}, phone={phone})")
    print()


async def test_fetch_appointments(context: dict) -> None:
    print("--- fetch_appointments ---")
    token = context["accessToken"]
    now = datetime.now()
    start_date = (now - timedelta(days=7)).strftime("%d-%m-%Y")
    end_date = (now + timedelta(days=30)).strftime("%d-%m-%Y")
    print(f"  Date range: {start_date} to {end_date}")
    result = await setmore_api.fetch_appointments(
        token, start_date=start_date, end_date=end_date, customer_details=True
    )
    print(f"  Success: {result.get('success')}")
    appointments = result.get("appointments") or []
    print(f"  Appointment count: {len(appointments)}")
    for appt in appointments[:10]:
        key = appt.get("key")
        start = appt.get("start_time")
        service = appt.get("service_name") or appt.get("service_key")
        staff = appt.get("staff_key")
        print(f"    - {start} | service={service} | staff={staff} (key={key})")
    if len(appointments) > 10:
        print(f"    ... and {len(appointments) - 10} more")
    print()


ALL_TESTS = {
    "fetch-company": test_fetch_company,
    "fetch-services": test_fetch_services,
    "fetch-service-categories": test_fetch_service_categories,
    "fetch-staff": test_fetch_staff,
    "fetch-slots": test_fetch_slots,
    "fetch-customer": test_fetch_customer,
    "fetch-appointments": test_fetch_appointments,
}


async def main(args: argparse.Namespace) -> int:
    print(f"=== Setmore API tests for: {BUSINESS_NUMBER} ===\n")
    context = await _resolve_context()
    print(f"Provider: {context.get('provider')}")
    print(f"Business: {(context.get('location') or {}).get('business_name')}\n")

    tests_to_run = [args.test] if args.test else list(ALL_TESTS.keys())

    for test_name in tests_to_run:
        fn = ALL_TESTS.get(test_name)
        if not fn:
            print(f"Unknown test: {test_name}")
            continue
        try:
            if test_name == "fetch-slots":
                await fn(context, service_name=args.service)
            elif test_name == "fetch-customer":
                await fn(context, first_name=args.first_name)
            else:
                await fn(context)
        except Exception as exc:
            print(f"ERROR in {test_name}: {exc}")
            import traceback
            traceback.print_exc()

    print("=== Setmore API tests complete ===")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test Setmore APIs for 510 405 4454")
    parser.add_argument(
        "--test",
        choices=list(ALL_TESTS.keys()),
        default=None,
        help="Run a specific test (default: run all).",
    )
    parser.add_argument("--service", default=None, help="Service name for fetch-slots test.")
    parser.add_argument("--first-name", default=None, help="First name for fetch-customer test.")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
