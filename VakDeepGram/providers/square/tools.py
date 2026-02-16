"""
Square-specific Strands tools.

These tools handle customer lookup, appointment booking / rescheduling,
and availability checking through the Square API.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from strands import tool
from strands.types.tools import ToolContext

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]

from utils import booking_helpers
from utils.phone import normalize_phone_number
from utils.square_helpers import parse_square_response, extract_square_cursor

from providers.common.helpers import (
    get_business_context,
    update_business_context,
    as_dict,
    parse_datetime,
    isoformat_utc,
    resolve_location_timezone,
    resolve_date_range,
    ensure_minimum_range,
    match_service_variation,
    resolve_staff_ids as _resolve_staff_ids,
    staff_display_name as _staff_display_name,
    resolve_available_staff as _resolve_available_staff,
    availability_supports_start,
    availability_team_member_ids,
    availability_window_minutes,
    format_availability_response,
    booking_segments as _booking_segments,
    booking_version as _booking_version,
    extract_booking_segment_details,
    suggest_services,
)
from providers.common.tools import COMMON_TOOLS
from providers.square.helpers import (
    get_client,
    get_access_context,
    find_customer_by_phone,
    collect_async_pager,
)

logger = logging.getLogger(__name__)


# ── Tools ─────────────────────────────────────────────────────────────────────

# Message to ask the customer before using their caller/call-in number (used when confirmation not yet given)
ASK_CUSTOMER_USE_CALLER_PHONE = (
    "Can I use the number you're calling or messaging from to look up your account or create one?"
)


@tool(context=True)
async def find_customer(
    tool_context: ToolContext,
    phone: Optional[str] = None,
    caller_number: Optional[str] = None,
    first_name: Optional[str] = None,
    email: Optional[str] = None,
    customer_confirmed_use_of_caller_phone: Optional[bool] = None,
) -> dict:
    """Look up a customer's account information by phone number.

    Use this before appointments or order lookups when you need a customer ID.
    Before using the caller's phone number (from the call or message), you MUST confirm with the customer
    (e.g. ask: "Can I use the number you're calling from to look up your account?"). Only pass
    customer_confirmed_use_of_caller_phone=True after they agree.
    Phone number: Format as +1XXXXXXXXXX (add +1 if not provided, remove spaces/dashes).
    """
    business_context = get_business_context(tool_context)
    if not any([phone, caller_number]):
        context_customer = business_context.get("customer")
        if context_customer:
            return {"success": True, "customer": as_dict(context_customer), "new_customer": False}
        phone = business_context.get("caller")
    phone = phone or caller_number
    if not phone:
        return {"error": "phone is required"}

    # Require explicit confirmation before using caller's phone from context
    caller_from_context = business_context.get("caller")
    if caller_from_context and normalize_phone_number(phone) == normalize_phone_number(caller_from_context):
        if customer_confirmed_use_of_caller_phone is not True:
            return {
                "success": False,
                "error": "Confirm with the customer before using their phone number.",
                "ask_customer": ASK_CUSTOMER_USE_CALLER_PHONE,
            }

    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx

    client = get_client(ctx["access_token"])
    normalized = normalize_phone_number(phone) or phone
    customer = await find_customer_by_phone(client, normalized)
    if customer:
        return {"success": True, "customer": customer, "new_customer": False}
    return {"success": False, "error": "Customer not found.", "new_customer": True}


@tool(context=True)
async def create_customer(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    caller_number: Optional[str] = None,
    customer_confirmed_use_of_caller_phone: Optional[bool] = None,
) -> dict:
    """Create a new customer in Square.

    Use this when find_customer returns no match and the customer wants to book.
    Before using the caller's phone number, confirm with the customer and pass
    customer_confirmed_use_of_caller_phone=True only after they agree.
    """
    business_context = get_business_context(tool_context)
    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx
    client = get_client(ctx["access_token"])

    phone = phone_number or caller_number or business_context.get("caller")
    if phone:
        caller_from_context = business_context.get("caller")
        if caller_from_context and normalize_phone_number(phone) == normalize_phone_number(caller_from_context):
            if customer_confirmed_use_of_caller_phone is not True:
                return {
                    "success": False,
                    "error": "Confirm with the customer before using their phone number.",
                    "ask_customer": ASK_CUSTOMER_USE_CALLER_PHONE,
                }
    if phone:
        normalized = normalize_phone_number(phone) or phone
        existing = await find_customer_by_phone(client, normalized)
        if existing:
            return {"success": True, "customer": existing, "new_customer": False, "message": "Customer already exists."}

    normalized_phone = normalize_phone_number(phone) if phone else None
    try:
        response = await client.customers.create(
            idempotency_key=str(uuid.uuid4()),
            given_name=first_name,
            family_name=last_name,
            phone_number=normalized_phone,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    parsed = parse_square_response(response)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}
    customer = parsed.get("payload", {}).get("customer")
    return {"success": True, "customer": as_dict(customer)}


@tool(context=True)
async def lookup_or_create_customer_using_caller(
    tool_context: ToolContext,
    customer_confirmed_use_of_caller_phone: bool,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> dict:
    """Look up customer by the caller's phone number; if not found, create an account with that number.

    Use this when the customer is calling or messaging and you want to find their account or create one.
    You MUST confirm with the customer first (e.g. 'Can I use the number you're calling from to look up
    your account or create one?'). Only pass customer_confirmed_use_of_caller_phone=True after they agree.
    If a customer is found, returns them. If not found and first_name and last_name are provided, creates
    a new customer with the caller's phone and returns. If not found and name is missing, returns a message
    asking for first and last name.
    """
    business_context = get_business_context(tool_context)
    caller = business_context.get("caller")
    if not caller:
        return {"success": False, "error": "No caller number available. Ask the customer for their phone number."}
    if customer_confirmed_use_of_caller_phone is not True:
        return {
            "success": False,
            "error": "Confirm with the customer before using their phone number.",
            "ask_customer": ASK_CUSTOMER_USE_CALLER_PHONE,
        }

    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx
    client = get_client(ctx["access_token"])
    normalized = normalize_phone_number(caller) or caller
    existing = await find_customer_by_phone(client, normalized)
    if existing:
        update_business_context(tool_context, {"customer": existing})
        return {"success": True, "customer": existing, "new_customer": False}

    if not first_name or not last_name:
        return {
            "success": False,
            "error": "Customer not found. To create an account I need your first and last name.",
            "need_first_name": not first_name,
            "need_last_name": not last_name,
        }

    result = await create_customer(
        tool_context,
        first_name=first_name,
        last_name=last_name,
        phone_number=caller,
        customer_confirmed_use_of_caller_phone=True,
    )
    if result.get("success") and result.get("customer"):
        update_business_context(tool_context, {"customer": result["customer"]})
    return result


@tool(context=True)
async def get_appointments(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Retrieve all appointments for a Square customer.

    Use this when a customer asks about their upcoming appointments.
    Always verify you have the customer's account first via find_customer.
    """
    business_context = get_business_context(tool_context)
    if not customer_id:
        return {"success": False, "error": "customer_id is required"}
    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    now = datetime.now(tzinfo) if tzinfo else datetime.now()

    client = get_client(ctx["access_token"])
    start_at_min = isoformat_utc(now - timedelta(days=1))
    end_at_max = isoformat_utc(now + timedelta(days=90))

    appointments: list[Dict[str, Any]] = []
    cursor = None
    while True:
        response = await client.bookings.list(
            customer_id=customer_id,
            start_at_min=start_at_min,
            start_at_max=end_at_max,
            cursor=cursor,
            limit=200,
        )
        parsed = parse_square_response(response)
        if not parsed.get("success"):
            return {"success": False, "error": parsed.get("error")}
        if parsed.get("payload", {}).get("iterable"):
            page_items = await collect_async_pager(response)
            appointments.extend(page_items)
            cursor = extract_square_cursor(response)
        else:
            payload = parsed.get("payload", {})
            appointments.extend(payload.get("bookings") or [])
            cursor = payload.get("cursor")
        if not cursor:
            break

    from providers.common.helpers import as_dict as _as_dict
    formatted: list[Dict[str, Any]] = []
    for booking in appointments:
        booking = _as_dict(booking)
        start_at = booking.get("start_at") or booking.get("startAt")
        start_local = None
        if start_at and tzinfo:
            try:
                start_local = datetime.fromisoformat(start_at.replace("Z", "+00:00")).astimezone(tzinfo)
            except ValueError:
                start_local = None
        segment_details = extract_booking_segment_details(booking)
        formatted.append({
            "appointment_id": booking.get("id"),
            "status": booking.get("status"),
            "start_at": start_at,
            "start_at_local": start_local.isoformat(timespec="seconds") if start_local else None,
            "service_variation_id": segment_details.get("service_variation_id"),
            "staff_id": segment_details.get("team_member_id"),
            "location_id": booking.get("location_id") or booking.get("locationId"),
        })

    return {"success": True, "appointments": formatted}


@tool(context=True)
async def get_orders(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Retrieve order history for a customer.

    Use this when a customer asks about their orders or order status.
    """
    _ = tool_context
    _ = customer_id
    now = datetime.now()
    return {
        "success": True,
        "orders": [
            {
                "order_id": "ORD0089",
                "date": (now - timedelta(days=4)).isoformat(timespec="seconds"),
                "status": "shipped",
                "amount": 129.99,
            }
        ],
    }


@tool(context=True)
async def check_availability(
    tool_context: ToolContext,
    start_date: str,
    service: str,
    end_date: Optional[str] = None,
    staff_ids: Optional[list] = None,
) -> dict:
    """Check available appointment slots within a date range.

    Use this when a customer wants to know available appointment times.
    start_date can be ISO format, a relative keyword (TODAY, NEXT_WEEK), or a weekday name.
    """
    business_context = get_business_context(tool_context)
    if not start_date:
        return {"success": False, "error": "start_date is required"}
    if not service:
        return {"success": False, "error": "service is required"}

    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx
    client = get_client(ctx["access_token"])
    location_id = ctx["location_id"]

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None

    start_at_local, end_at_local = resolve_date_range(start_date, end_date, tzinfo)
    start_at_local, end_at_local = ensure_minimum_range(start_at_local, end_at_local)
    start_at = isoformat_utc(start_at_local)
    end_at = isoformat_utc(end_at_local)

    resolved_staff, unmatched = _resolve_staff_ids(business_context, staff_ids or [])
    if staff_ids and (not resolved_staff or unmatched):
        return {"success": False, "error": "Requested staff not found.", "unmatched_staff": unmatched}

    service_variation_id, _, _ = match_service_variation(business_context, service)
    if not service_variation_id:
        suggestions = suggest_services(business_context, service)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    filter_payload: dict = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": service_variation_id}],
    }
    if resolved_staff:
        filter_payload["segment_filters"][0]["team_member_id_filter"] = {"any": resolved_staff}

    response = await client.bookings.search_availability(query={"filter": filter_payload})
    parsed = parse_square_response(response)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}

    availabilities = parsed.get("payload", {}).get("availabilities") or []
    availability = format_availability_response(availabilities, tzinfo)
    available_staff = _resolve_available_staff(business_context, availabilities)
    if resolved_staff:
        sid_set = set(resolved_staff)
        available_staff = [m for m in available_staff if m.get("id") in sid_set]

    return {
        "success": True,
        "availability_mode": availability.get("mode"),
        "slots": availability.get("slots"),
        "ranges": availability.get("ranges"),
        "available_staff": available_staff,
    }


@tool(context=True)
async def create_appointment(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    customer_id: str,
    date: str,
    service: str,
    staff_id: Optional[str] = None,
    phone_number: Optional[str] = None,
    caller_number: Optional[str] = None,
) -> dict:
    """Schedule a new appointment for a customer.

    Before scheduling:
    1. Ask for a preferred day/date
    2. Check availability using check_availability
    3. Confirm date/time and service type with the customer
    4. Collect first and last name
    5. If the customer exists, pass their customer_id; otherwise create first.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = get_business_context(tool_context)
    if not all([first_name, last_name, date, service]):
        return {"success": False, "error": "first_name, last_name, date, and service are required"}

    phone = phone_number or caller_number or business_context.get("caller")
    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx
    client = get_client(ctx["access_token"])
    location_id = ctx["location_id"]

    # Resolve / create customer
    resolved_customer_id = customer_id
    if not resolved_customer_id and phone:
        normalized = normalize_phone_number(phone) or phone
        existing = await find_customer_by_phone(client, normalized)
        if existing:
            resolved_customer_id = existing.get("id")
        else:
            try:
                created = await client.customers.create(
                    idempotency_key=str(uuid.uuid4()),
                    given_name=first_name,
                    family_name=last_name,
                    phone_number=normalized,
                )
            except Exception as exc:
                return {"success": False, "error": str(exc)}
            parsed = parse_square_response(created)
            if not parsed.get("success"):
                return {"success": False, "error": parsed.get("error")}
            resolved_customer_id = (parsed.get("payload", {}).get("customer") or {}).get("id")

    if not resolved_customer_id:
        return {"success": False, "error": "Customer not found and could not be created."}

    service_variation_id, duration_minutes, service_version = match_service_variation(business_context, service)
    if not service_variation_id:
        suggestions = suggest_services(business_context, service)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    start_dt = parse_datetime(date)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    effective_tzinfo = tzinfo or start_dt.tzinfo
    start_at = isoformat_utc(start_dt)

    # Verify availability window
    tolerance = availability_window_minutes(service, duration_minutes)
    avail_start = start_dt - timedelta(minutes=tolerance)
    avail_end = start_dt + timedelta(minutes=tolerance + (duration_minutes or 0))
    avail_filter: dict = {
        "start_at_range": {"start_at": isoformat_utc(avail_start), "end_at": isoformat_utc(avail_end)},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": service_variation_id}],
    }
    avail_resp = await client.bookings.search_availability(query={"filter": avail_filter})
    avail_parsed = parse_square_response(avail_resp)
    if not avail_parsed.get("success"):
        return {"success": False, "error": avail_parsed.get("error")}

    availabilities = avail_parsed.get("payload", {}).get("availabilities") or []
    matching = [a for a in availabilities if availability_supports_start(a, start_dt, duration_minutes, effective_tzinfo, tolerance)]
    avail_ids: set[str] = set()
    for a in matching:
        avail_ids.update(availability_team_member_ids(a))

    if staff_id:
        if staff_id not in avail_ids:
            return {"success": False, "error": "Selected staff is not available around the requested time."}
    else:
        for member in business_context.get("staff") or []:
            mid = member.get("id")
            if mid in avail_ids and member.get("status") == "ACTIVE":
                staff_id = mid
                break
        if not staff_id and avail_ids:
            staff_id = sorted(avail_ids)[0]
        if not staff_id:
            return {"success": False, "error": "No staff availability around the requested time."}

    staff_name = _staff_display_name(business_context, staff_id)
    segment: dict = {"service_variation_id": service_variation_id, "team_member_id": staff_id}
    if service_version:
        segment["service_variation_version"] = service_version
    if duration_minutes:
        segment["duration_minutes"] = duration_minutes

    booking_payload: dict = {
        "start_at": start_at,
        "location_id": location_id,
        "customer_id": resolved_customer_id,
        "appointment_segments": [segment],
    }
    created_booking = await client.bookings.create(booking=booking_payload, idempotency_key=str(uuid.uuid4()))
    created_parsed = parse_square_response(created_booking)
    if not created_parsed.get("success"):
        return {"success": False, "error": created_parsed.get("error")}
    booking = as_dict(created_parsed.get("payload", {}).get("booking") or {})

    return {
        "success": True,
        "appointment": {
            "appointment_id": booking.get("id"),
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone,
            "customer_id": resolved_customer_id,
            "date": booking.get("start_at") or start_at,
            "service": service,
            "staff_id": staff_id,
            "staff_name": staff_name,
            "status": booking.get("status") or "confirmed",
        },
    }


@tool(context=True)
async def update_appointment(
    tool_context: ToolContext,
    booking_id: str,
    date: str,
    service: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> dict:
    """Reschedule an existing appointment.

    Before rescheduling:
    1. Confirm the booking_id
    2. Confirm the desired new date/time and service
    3. Verify availability for the new slot
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = get_business_context(tool_context)
    if not booking_id or not date:
        return {"success": False, "error": "booking_id and date are required"}

    ctx = get_access_context(business_context)
    if not ctx.get("success"):
        return ctx
    client = get_client(ctx["access_token"])
    location_id = ctx["location_id"]

    booking_resp = await client.bookings.retrieve(booking_id=booking_id)
    booking_parsed = parse_square_response(booking_resp)
    if not booking_parsed.get("success"):
        return {"success": False, "error": booking_parsed.get("error")}
    booking = as_dict(booking_parsed.get("payload", {}).get("booking") or {})
    version = _booking_version(booking)
    if version is None:
        return {"success": False, "error": "Booking version not available."}

    segment_details = extract_booking_segment_details(booking)
    if staff_name and not staff_id:
        resolved, unmatched = _resolve_staff_ids(business_context, [staff_name])
        if unmatched or not resolved:
            return {"success": False, "error": "Requested staff not found.", "unmatched_staff": unmatched}
        staff_id = resolved[0]
    if not staff_id:
        staff_id = segment_details.get("team_member_id")
    if not staff_id:
        return {"success": False, "error": "staff_id is required for booking update."}

    if service:
        svi, dur, sver = match_service_variation(business_context, service)
    else:
        svi = segment_details.get("service_variation_id")
        dur = segment_details.get("duration_minutes")
        sver = segment_details.get("service_variation_version")
    if not svi:
        suggestions = suggest_services(business_context, service)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    start_dt = parse_datetime(date)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    effective_tzinfo = tzinfo or start_dt.tzinfo
    start_at = isoformat_utc(start_dt)

    tolerance = availability_window_minutes(service, dur)
    avail_start = start_dt - timedelta(minutes=tolerance)
    avail_end = start_dt + timedelta(minutes=tolerance + (dur or 0))
    avail_filter: dict = {
        "start_at_range": {"start_at": isoformat_utc(avail_start), "end_at": isoformat_utc(avail_end)},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": svi, "team_member_id_filter": {"any": [staff_id]}}],
    }
    avail_resp = await client.bookings.search_availability(query={"filter": avail_filter})
    avail_parsed = parse_square_response(avail_resp)
    if not avail_parsed.get("success"):
        return {"success": False, "error": avail_parsed.get("error")}

    availabilities = avail_parsed.get("payload", {}).get("availabilities") or []
    matching = [a for a in availabilities if availability_supports_start(a, start_dt, dur, effective_tzinfo, tolerance)]
    avail_ids: set[str] = set()
    for a in matching:
        avail_ids.update(availability_team_member_ids(a))
    if staff_id not in avail_ids:
        return {"success": False, "error": "Selected staff is not available around the requested time."}

    segment: dict = {"service_variation_id": svi, "team_member_id": staff_id}
    if sver:
        segment["service_variation_version"] = sver
    if dur:
        segment["duration_minutes"] = dur

    update_payload: dict = {
        "id": booking_id,
        "version": version,
        "start_at": start_at,
        "location_id": location_id,
        "appointment_segments": [segment],
    }
    cid = booking.get("customer_id") or booking.get("customerId")
    if cid:
        update_payload["customer_id"] = cid

    update_resp = await client.bookings.update(booking_id=booking_id, booking=update_payload)
    update_parsed = parse_square_response(update_resp)
    if not update_parsed.get("success"):
        return {"success": False, "error": update_parsed.get("error")}
    updated = as_dict(update_parsed.get("payload", {}).get("booking") or {})

    return {
        "success": True,
        "appointment": {
            "appointment_id": updated.get("id") or booking_id,
            "date": updated.get("start_at") or start_at,
            "service": service,
            "staff_id": staff_id,
            "staff_name": _staff_display_name(business_context, staff_id),
            "status": updated.get("status") or booking.get("status"),
        },
    }


# ── Tool list ─────────────────────────────────────────────────────────────────

TOOLS = [
    find_customer,
    create_customer,
    lookup_or_create_customer_using_caller,
    get_appointments,
    get_orders,
    check_availability,
    create_appointment,
    update_appointment,
    *COMMON_TOOLS,
]
