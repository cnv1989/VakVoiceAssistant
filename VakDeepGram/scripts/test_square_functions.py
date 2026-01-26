#!/usr/bin/env python3
"""
Manual Square API smoke tests for VakDeepGram.

Examples:
  python scripts/test_square_functions.py list-locations --access-token ... --environment sandbox
  python scripts/test_square_functions.py get-appointments --access-token ... --environment production \
    --customer-id CUST... --start-at-min 2024-01-01T00:00:00Z --start-at-max 2024-03-01T00:00:00Z
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from typing import Any, Dict, Optional, Tuple

from square import AsyncSquare

try:
    from square.environment import SquareEnvironment
except Exception:
    SquareEnvironment = None


def _square_environment(value: str):
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if value == "sandbox" else SquareEnvironment.PRODUCTION
    return value


def _parse_square_response(response: Any) -> Dict[str, Any]:
    if hasattr(response, "__aiter__"):
        return {
            "success": True,
            "payload": {"iterable": True},
        }
    if hasattr(response, "is_error"):
        if response.is_error():
            return {"success": False, "error": response.errors}
        payload = response.body or {}
    elif hasattr(response, "model_dump"):
        payload = response.model_dump()
        if payload.get("errors"):
            return {"success": False, "error": payload.get("errors")}
    elif isinstance(response, dict):
        payload = response
        if payload.get("errors"):
            return {"success": False, "error": payload.get("errors")}
    else:
        return {"success": False, "error": f"Unexpected Square response type: {type(response)}"}
    return {"success": True, "payload": payload}


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _print_result(name: str, result: Dict[str, Any]) -> None:
    payload = {"function": name, "result": _as_dict(result)}
    print(json.dumps(payload, indent=2, default=str))


async def _resolve_location_id(client: AsyncSquare, location_id: Optional[str]) -> str:
    if location_id:
        return location_id
    response = await client.locations.list()
    parsed = _parse_square_response(response)
    if not parsed.get("success"):
        raise RuntimeError(f"Failed to list locations: {parsed.get('error')}")
    locations = parsed.get("payload", {}).get("locations") or []
    if not locations:
        raise RuntimeError("No Square locations available for this token.")
    return locations[0].get("id")


async def _resolve_service_variation_id(
    client: AsyncSquare,
    location_id: str,
    service_name: str,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    response = await client.catalog.search_items(
        enabled_location_ids=[location_id],
        product_types=["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"],
    )
    parsed = _parse_square_response(response)
    if not parsed.get("success"):
        return None, None, None
    items = parsed.get("payload", {}).get("items") or []
    target = service_name.strip().lower()
    for item in items:
        item_data = item.get("item_data") or {}
        item_name = (item_data.get("name") or item.get("name") or "").strip().lower()
        for variation in item_data.get("variations") or []:
            variation_data = variation.get("item_variation_data") or {}
            variation_name = (variation_data.get("name") or "").strip().lower()
            if target in item_name or target in variation_name:
                duration_ms = variation_data.get("service_duration")
                duration_minutes = int(duration_ms / 60000) if duration_ms else None
                return variation.get("id"), duration_minutes, variation.get("version")
    return None, None, None


def _require_mutations(enabled: bool, name: str) -> bool:
    if enabled:
        return True
    _print_result(name, {"success": False, "error": "Mutations disabled. Pass --allow-mutations."})
    return False


async def _run_list_locations(client: AsyncSquare) -> None:
    response = await client.locations.list()
    _print_result("list_locations", _parse_square_response(response))


async def _run_get_location(client: AsyncSquare, location_id: str) -> None:
    response = await client.locations.get(location_id)
    _print_result("get_location", _parse_square_response(response))


async def _run_list_services(client: AsyncSquare, location_id: str) -> None:
    response = await client.catalog.search_items(
        enabled_location_ids=[location_id],
        product_types=["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"],
    )
    _print_result("list_services", _parse_square_response(response))


async def _run_list_staff(client: AsyncSquare, location_id: str) -> None:
    try:
        from square.types.search_team_members_query import SearchTeamMembersQuery
        from square.types.search_team_members_filter import SearchTeamMembersFilter
    except Exception:
        _print_result("list_staff", {"success": False, "error": "Square team member query types unavailable."})
        return
    query = SearchTeamMembersQuery(
        filter=SearchTeamMembersFilter(location_ids=[location_id], status="ACTIVE"),
    )
    response = await client.team_members.search(query=query, limit=200)
    _print_result("list_staff", _parse_square_response(response))


async def _run_list_customers(client: AsyncSquare) -> None:
    response = await client.customers.list(limit=100)
    parsed = _parse_square_response(response)
    if parsed.get("payload", {}).get("iterable"):
        customers: list[dict] = []
        async for customer in response:
            customers.append(_as_dict(customer))
        _print_result("list_customers", {"success": True, "customers": customers})
        return
    _print_result("list_customers", parsed)


async def _run_find_customer_by_phone(client: AsyncSquare, phone: str) -> None:
    response = await client.customers.list(limit=100)
    parsed = _parse_square_response(response)
    customers: list[dict] = []
    if parsed.get("payload", {}).get("iterable"):
        async for customer in response:
            customers.append(customer)
    elif parsed.get("success"):
        customers = parsed.get("payload", {}).get("customers") or []
    else:
        _print_result("find_customer_by_phone", parsed)
        return
    matches = []
    for cust in customers:
        cust_dict = _as_dict(cust)
        if isinstance(cust_dict, dict) and cust_dict.get("phone_number") == phone:
            matches.append(cust_dict)
    _print_result("find_customer_by_phone", {"success": True, "matches": matches})


async def _run_create_customer(
    client: AsyncSquare,
    first_name: str,
    last_name: str,
    phone: Optional[str],
    allow_mutations: bool,
) -> None:
    if not _require_mutations(allow_mutations, "create_customer"):
        return
    if not first_name or not last_name or not phone:
        _print_result("create_customer", {"success": False, "error": "first_name, last_name, phone required"})
        return
    response = await client.customers.create(
        idempotency_key=str(uuid.uuid4()),
        given_name=first_name,
        family_name=last_name,
        phone_number=phone,
    )
    _print_result("create_customer", _parse_square_response(response))


async def _run_get_appointments(
    client: AsyncSquare,
    customer_id: str,
    start_at_min: Optional[str],
    start_at_max: Optional[str],
) -> None:
    if not customer_id:
        _print_result("get_appointments", {"success": False, "error": "customer_id required"})
        return
    response = await client.bookings.list(
        customer_id=customer_id,
        start_at_min=start_at_min,
        start_at_max=start_at_max,
        limit=200,
    )
    parsed = _parse_square_response(response)
    if parsed.get("payload", {}).get("iterable"):
        bookings: list[dict] = []
        async for booking in response:
            bookings.append(_as_dict(booking))
        _print_result("get_appointments", {"success": True, "bookings": bookings})
        return
    _print_result("get_appointments", parsed)


async def _run_check_availability(
    client: AsyncSquare,
    location_id: str,
    start_at: str,
    end_at: str,
    service_variation_id: Optional[str],
    service_name: Optional[str],
    staff_ids: Optional[list[str]],
) -> None:
    if not start_at or not end_at:
        _print_result("check_availability", {"success": False, "error": "start_at and end_at required"})
        return
    resolved_id = service_variation_id
    duration_minutes = None
    service_version = None
    if not resolved_id and service_name:
        resolved_id, duration_minutes, service_version = await _resolve_service_variation_id(
            client, location_id, service_name
        )
    if not resolved_id:
        _print_result("check_availability", {"success": False, "error": "service_variation_id required"})
        return

    filter_payload = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": resolved_id}],
    }
    if staff_ids:
        filter_payload["segment_filters"][0]["team_member_id_filter"] = {"any": staff_ids}
    response = await client.bookings.search_availability(query={"filter": filter_payload})
    result = _parse_square_response(response)
    if service_version or duration_minutes:
        result["service_match"] = {
            "service_variation_id": resolved_id,
            "service_variation_version": service_version,
            "duration_minutes": duration_minutes,
        }
    _print_result("check_availability", result)


async def _run_create_appointment(
    client: AsyncSquare,
    location_id: str,
    start_at: str,
    customer_id: str,
    staff_id: str,
    service_variation_id: Optional[str],
    service_name: Optional[str],
    allow_mutations: bool,
) -> None:
    if not _require_mutations(allow_mutations, "create_appointment"):
        return
    if not start_at or not customer_id or not staff_id:
        _print_result(
            "create_appointment",
            {"success": False, "error": "start_at, customer_id, staff_id required"},
        )
        return
    resolved_id = service_variation_id
    _, duration_minutes, service_version = None, None, None
    if not resolved_id and service_name:
        resolved_id, duration_minutes, service_version = await _resolve_service_variation_id(
            client, location_id, service_name
        )
    if not resolved_id:
        _print_result("create_appointment", {"success": False, "error": "service_variation_id required"})
        return
    segment = {
        "service_variation_id": resolved_id,
        "team_member_id": staff_id,
    }
    if service_version:
        segment["service_variation_version"] = service_version
    if duration_minutes:
        segment["duration_minutes"] = duration_minutes
    response = await client.bookings.create(
        booking={
            "start_at": start_at,
            "location_id": location_id,
            "customer_id": customer_id,
            "appointment_segments": [segment],
        },
        idempotency_key=str(uuid.uuid4()),
    )
    _print_result("create_appointment", _parse_square_response(response))


async def _run_update_appointment(
    client: AsyncSquare,
    booking_id: str,
    start_at: Optional[str],
    staff_id: Optional[str],
    service_variation_id: Optional[str],
    allow_mutations: bool,
) -> None:
    if not _require_mutations(allow_mutations, "update_appointment"):
        return
    if not booking_id:
        _print_result("update_appointment", {"success": False, "error": "booking_id required"})
        return
    current = await client.bookings.retrieve(booking_id=booking_id)
    parsed = _parse_square_response(current)
    if not parsed.get("success"):
        _print_result("update_appointment", parsed)
        return
    booking = parsed.get("payload", {}).get("booking") or {}
    version = booking.get("version")
    location_id = booking.get("location_id") or booking.get("locationId")
    customer_id = booking.get("customer_id") or booking.get("customerId")
    segment = (booking.get("appointment_segments") or [None])[0] or {}
    service_id = service_variation_id or segment.get("service_variation_id")
    team_member_id = staff_id or segment.get("team_member_id")
    if version is None or not location_id or not customer_id or not service_id or not team_member_id:
        _print_result("update_appointment", {"success": False, "error": "booking missing fields"})
        return

    update_payload = {
        "id": booking_id,
        "version": version,
        "location_id": location_id,
        "customer_id": customer_id,
        "appointment_segments": [
            {
                "service_variation_id": service_id,
                "team_member_id": team_member_id,
            }
        ],
    }
    if start_at:
        update_payload["start_at"] = start_at
    response = await client.bookings.update(booking_id=booking_id, booking=update_payload)
    _print_result("update_appointment", _parse_square_response(response))


async def _main_async(args: argparse.Namespace) -> int:
    if not args.access_token or not args.environment:
        missing = []
        if not args.access_token:
            missing.append("access_token")
        if not args.environment:
            missing.append("environment")
        print(f"Missing required settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    client = AsyncSquare(token=args.access_token, environment=_square_environment(args.environment))

    if args.command in {"list-locations"}:
        await _run_list_locations(client)
        return 0

    location_id = await _resolve_location_id(client, args.location_id)

    if args.command == "get-location":
        await _run_get_location(client, location_id)
    elif args.command == "list-services":
        await _run_list_services(client, location_id)
    elif args.command == "list-staff":
        await _run_list_staff(client, location_id)
    elif args.command == "list-customers":
        await _run_list_customers(client)
    elif args.command == "find-customer":
        if not args.phone:
            _print_result("find_customer_by_phone", {"success": False, "error": "phone required"})
            return 2
        await _run_find_customer_by_phone(client, args.phone)
    elif args.command == "create-customer":
        await _run_create_customer(
            client,
            args.first_name,
            args.last_name,
            args.phone,
            args.allow_mutations,
        )
    elif args.command == "get-appointments":
        await _run_get_appointments(client, args.customer_id, args.start_at_min, args.start_at_max)
    elif args.command == "check-availability":
        await _run_check_availability(
            client,
            location_id,
            args.start_at,
            args.end_at,
            args.service_variation_id,
            args.service,
            args.staff_ids,
        )
    elif args.command == "create-appointment":
        await _run_create_appointment(
            client,
            location_id,
            args.start_at,
            args.customer_id,
            args.staff_id,
            args.service_variation_id,
            args.service,
            args.allow_mutations,
        )
    elif args.command == "update-appointment":
        await _run_update_appointment(
            client,
            args.booking_id,
            args.start_at,
            args.staff_id,
            args.service_variation_id,
            args.allow_mutations,
        )
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--access-token",
        default=os.environ.get("SQUARE_ACCESS_TOKEN"),
        help="Square access token (defaults to env SQUARE_ACCESS_TOKEN).",
    )
    common.add_argument(
        "--environment",
        default=os.environ.get("SQUARE_ENVIRONMENT"),
        choices=("sandbox", "production"),
        help="Square environment (defaults to env SQUARE_ENVIRONMENT).",
    )
    common.add_argument("--location-id", help="Square location ID (optional).")
    common.add_argument("--phone", help="Phone number to search/create.")
    common.add_argument("--email", help="Customer email (unused for now).")
    common.add_argument("--customer-id", help="Square customer ID.")
    common.add_argument("--first-name", help="Customer first name.")
    common.add_argument("--last-name", help="Customer last name.")
    common.add_argument("--service", help="Service name to match.")
    common.add_argument("--service-variation-id", help="Square service variation ID.")
    common.add_argument("--staff-id", help="Staff ID to book/update.")
    common.add_argument("--start-at", help="Start datetime (ISO format, UTC).")
    common.add_argument("--end-at", help="End datetime (ISO format, UTC).")
    common.add_argument("--start-at-min", help="Bookings list start_at_min.")
    common.add_argument("--start-at-max", help="Bookings list start_at_max.")
    common.add_argument("--booking-id", help="Booking ID to update.")
    common.add_argument(
        "--staff-ids",
        nargs="*",
        default=None,
        help="Optional staff IDs for availability.",
    )
    common.add_argument(
        "--allow-mutations",
        action="store_true",
        help="Allow create/update calls that change data.",
    )

    parser = argparse.ArgumentParser(description="Manual Square API smoke tests.", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "list-locations",
        "get-location",
        "list-services",
        "list-staff",
        "list-customers",
        "find-customer",
        "create-customer",
        "get-appointments",
        "check-availability",
        "create-appointment",
        "update-appointment",
    ):
        subparsers.add_parser(name, parents=[common], add_help=False)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
