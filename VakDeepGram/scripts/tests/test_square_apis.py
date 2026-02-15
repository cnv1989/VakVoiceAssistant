#!/usr/bin/env python3
"""
Test Square API calls using the resolved context for business number 510 405 4454.

If the provider for the number is 'square', tests: list locations, list services,
list staff, list customers, check availability.

If the provider is 'setmore', this script exits with a notice (use
test_setmore_apis.py instead).

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_square_apis
  python -m scripts.tests.test_square_apis --test list-services
  python -m scripts.tests.test_square_apis --test check-availability --service "Haircut"
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
from utils.square_helpers import get_square_environment, parse_square_response

BUSINESS_NUMBER = "510 405 4454"


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


def _as_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


async def _resolve_context() -> dict:
    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        print(f"FAIL: Cannot resolve context: {context.get('error')}")
        sys.exit(1)
    provider = context.get("provider", "square")
    if provider != "square":
        print(f"INFO: Provider for {BUSINESS_NUMBER} is '{provider}', not 'square'.")
        print("This script is designed for Square businesses. Use test_setmore_apis.py instead.")
        sys.exit(0)
    return context


async def test_list_locations(context: dict) -> None:
    from square import AsyncSquare

    print("--- list_locations ---")
    token = context["accessToken"]
    client = AsyncSquare(token=token, environment=get_square_environment())
    response = await client.locations.list()
    parsed = parse_square_response(response)
    print(f"Success: {parsed.get('success')}")
    locations = parsed.get("payload", {}).get("locations") or []
    print(f"Location count: {len(locations)}")
    for loc in locations[:5]:
        loc = _as_dict(loc)
        print(f"  - {loc.get('name')} (id={loc.get('id')}, tz={loc.get('timezone')})")
    print()


async def test_list_services(context: dict) -> None:
    from square import AsyncSquare

    print("--- list_services ---")
    token = context["accessToken"]
    location_id = context["locationId"]
    client = AsyncSquare(token=token, environment=get_square_environment())
    response = await client.catalog.search_items(
        enabled_location_ids=[location_id],
        product_types=["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"],
    )
    parsed = parse_square_response(response)
    print(f"Success: {parsed.get('success')}")
    items = parsed.get("payload", {}).get("items") or []
    print(f"Service items: {len(items)}")
    for item in items[:10]:
        item = _as_dict(item)
        name = (item.get("item_data") or {}).get("name") or item.get("name")
        print(f"  - {name}")
    print()


async def test_list_staff(context: dict) -> None:
    from square import AsyncSquare

    print("--- list_staff ---")
    token = context["accessToken"]
    location_id = context["locationId"]
    client = AsyncSquare(token=token, environment=get_square_environment())
    try:
        from square.types.search_team_members_query import SearchTeamMembersQuery
        from square.types.search_team_members_filter import SearchTeamMembersFilter
    except Exception:
        print("SKIP: Square team member query types unavailable.")
        return
    query = SearchTeamMembersQuery(
        filter=SearchTeamMembersFilter(location_ids=[location_id], status="ACTIVE"),
    )
    response = await client.team_members.search(query=query, limit=200)
    parsed = parse_square_response(response)
    print(f"Success: {parsed.get('success')}")
    members = parsed.get("payload", {}).get("team_members") or []
    print(f"Staff count: {len(members)}")
    for member in members[:10]:
        member = _as_dict(member)
        print(f"  - {member.get('given_name', '')} {member.get('family_name', '')} (id={member.get('id')})")
    print()


async def test_list_customers(context: dict) -> None:
    from square import AsyncSquare

    print("--- list_customers ---")
    token = context["accessToken"]
    client = AsyncSquare(token=token, environment=get_square_environment())
    response = await client.customers.list(limit=20)
    parsed = parse_square_response(response)
    if parsed.get("payload", {}).get("iterable"):
        customers = []
        async for cust in response:
            customers.append(_as_dict(cust))
            if len(customers) >= 20:
                break
    else:
        customers = parsed.get("payload", {}).get("customers") or []
    print(f"Success: {parsed.get('success')}")
    print(f"Customer count (first page): {len(customers)}")
    for cust in customers[:10]:
        print(f"  - {cust.get('given_name', '')} {cust.get('family_name', '')} (phone={cust.get('phone_number')})")
    print()


async def test_check_availability(context: dict, service_name: str | None = None) -> None:
    from square import AsyncSquare

    print("--- check_availability ---")
    token = context["accessToken"]
    location_id = context["locationId"]

    # Match service
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
        print("SKIP: No services to test availability.")
        return

    service_variation_id = None
    for var in service_item.get("variations") or []:
        service_variation_id = var.get("id")
        if service_variation_id:
            break
    if not service_variation_id:
        print(f"SKIP: No variation ID for service '{service_item.get('name')}'")
        return

    client = AsyncSquare(token=token, environment=get_square_environment())
    now = datetime.utcnow()
    start_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_at = (now + timedelta(days=2)).replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"  Service: {service_item.get('name')} (variation={service_variation_id})")
    print(f"  Range: {start_at} to {end_at}")

    filter_payload = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": service_variation_id}],
    }
    response = await client.bookings.search_availability(query={"filter": filter_payload})
    parsed = parse_square_response(response)
    print(f"  Success: {parsed.get('success')}")
    availabilities = parsed.get("payload", {}).get("availabilities") or []
    print(f"  Availability slots: {len(availabilities)}")
    for avail in availabilities[:10]:
        avail = _as_dict(avail)
        print(f"    - {avail.get('start_at')}")
    if len(availabilities) > 10:
        print(f"    ... and {len(availabilities) - 10} more")
    print()


ALL_TESTS = {
    "list-locations": test_list_locations,
    "list-services": test_list_services,
    "list-staff": test_list_staff,
    "list-customers": test_list_customers,
    "check-availability": test_check_availability,
}


async def main(args: argparse.Namespace) -> int:
    print(f"=== Square API tests for: {BUSINESS_NUMBER} ===\n")
    context = await _resolve_context()
    print(f"Provider: {context.get('provider')}")
    print(f"Location: {context.get('locationId')}\n")

    tests_to_run = [args.test] if args.test else list(ALL_TESTS.keys())

    for test_name in tests_to_run:
        fn = ALL_TESTS.get(test_name)
        if not fn:
            print(f"Unknown test: {test_name}")
            continue
        try:
            if test_name == "check-availability":
                await fn(context, service_name=args.service)
            else:
                await fn(context)
        except Exception as exc:
            print(f"ERROR in {test_name}: {exc}")
            import traceback
            traceback.print_exc()

    print("=== Square API tests complete ===")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test Square APIs for 510 405 4454")
    parser.add_argument(
        "--test",
        choices=list(ALL_TESTS.keys()),
        default=None,
        help="Run a specific test (default: run all).",
    )
    parser.add_argument("--service", default=None, help="Service name for check-availability test.")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
