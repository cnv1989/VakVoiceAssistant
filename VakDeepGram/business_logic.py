"""
Business logic for agent function calls.
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional
import uuid

from square import AsyncSquare
try:
    from square.environment import SquareEnvironment
except Exception:  # pragma: no cover - optional dependency behavior
    SquareEnvironment = None

import config
from connection_store import (
    fetch_square_customer_by_phone,
    get_connection_context,
    normalize_phone_number,
)
from twilio.rest import Client as TwilioClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

logger = logging.getLogger(__name__)


def _square_environment():
    logger.debug("business_logic._square_environment called")
    env_name = config.settings.square_environment
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if env_name == "sandbox" else SquareEnvironment.PRODUCTION
    return "sandbox" if env_name == "sandbox" else "production"


def _parse_square_response(response: Any) -> Dict[str, Any]:
    logger.debug("business_logic._parse_square_response called (type=%s)", type(response))
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
        return {"success": False, "error": "Unexpected Square response type."}
    return {"success": True, "payload": payload}


def _select_service_variation_id(context: Dict[str, Any]) -> Optional[str]:
    logger.debug("business_logic._select_service_variation_id called")
    services = context.get("services") or []
    for item in services:
        item_data = item.get("item_data") or {}
        for variation in item_data.get("variations") or []:
            variation_id = variation.get("id")
            if variation_id:
                return variation_id
    return None


def _select_team_member_id(context: Dict[str, Any]) -> Optional[str]:
    logger.debug("business_logic._select_team_member_id called")
    staff = context.get("staff") or []
    for member in staff:
        if member.get("status") == "ACTIVE" and member.get("id"):
            return member.get("id")
    for member in staff:
        if member.get("id"):
            return member.get("id")
    return None


def _match_service_variation(
    context: Dict[str, Any],
    service_name: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    logger.debug("business_logic._match_service_variation called (service=%s)", service_name)
    if not service_name:
        return _select_service_variation_id(context), None, None
    target = service_name.strip().lower()
    services = context.get("services") or []
    for item in services:
        item_data = item.get("item_data") or {}
        item_name = (item_data.get("name") or item.get("name") or "").strip().lower()
        for variation in item_data.get("variations") or []:
            variation_data = variation.get("item_variation_data") or {}
            variation_name = (variation_data.get("name") or "").strip().lower()
            if target in item_name or target in variation_name:
                duration_ms = variation_data.get("service_duration")
                duration_minutes = int(duration_ms / 60000) if duration_ms else None
                version = variation.get("version")
                return variation.get("id"), duration_minutes, version
    fallback_id = _select_service_variation_id(context)
    fallback_version = None
    services = context.get("services") or []
    for item in services:
        item_data = item.get("item_data") or {}
        for variation in item_data.get("variations") or []:
            if variation.get("id") == fallback_id:
                fallback_version = variation.get("version")
                break
    return fallback_id, None, fallback_version


def _normalize_iso(value: str) -> str:
    logger.debug("business_logic._normalize_iso called (value=%s)", value)
    return value.replace("Z", "+00:00")


def _parse_datetime(value: str) -> datetime:
    logger.debug("business_logic._parse_datetime called (value=%s)", value)
    return datetime.fromisoformat(_normalize_iso(value))


def _isoformat_utc(value: datetime) -> str:
    logger.debug("business_logic._isoformat_utc called (value=%s)", value)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _start_of_day(dt_value: datetime) -> datetime:
    logger.debug("business_logic._start_of_day called (value=%s)", dt_value)
    return dt_value.replace(hour=0, minute=0, second=0, microsecond=0)


def _ensure_minimum_range(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    logger.debug(
        "business_logic._ensure_minimum_range called (start=%s end=%s)",
        start_at,
        end_at,
    )
    if end_at <= start_at or end_at - start_at < timedelta(days=1):
        end_at = start_at + timedelta(days=1)
    if end_at - start_at > timedelta(days=32):
        end_at = start_at + timedelta(days=32)
    return start_at, end_at


def _normalize_booking_start_at(value: str, tzinfo) -> str:
    logger.debug("business_logic._normalize_booking_start_at called (value=%s tz=%s)", value, tzinfo)
    start_dt = _parse_datetime(value)
    if start_dt.tzinfo is None and tzinfo:
        start_dt = start_dt.replace(tzinfo=tzinfo)
    return _isoformat_utc(start_dt)


async def create_square_customer(
    client: AsyncSquare,
    first_name: str,
    last_name: str,
    phone_number: Optional[str],
) -> Dict[str, Any]:
    normalized_phone = normalize_phone_number(phone_number) if phone_number else None
    logger.debug("business_logic.create_square_customer called (phone=%s)", normalized_phone)
    if not normalized_phone:
        return {"success": False, "error": "phone_number is required for customer creation."}
    kwargs = {
        "idempotency_key": str(uuid.uuid4()),
        "given_name": first_name,
        "family_name": last_name,
    }
    kwargs["phone_number"] = normalized_phone
    response = await client.customers.create(**kwargs)
    parsed = _parse_square_response(response)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}
    customer = parsed.get("payload", {}).get("customer")
    return {"success": True, "customer": customer}


async def create_customer(
    connection_id: Optional[str],
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a customer in Square for the current connection."""
    logger.info(
        "business_logic.create_customer called (connection_id=%s phone=%s)",
        connection_id,
        phone_number,
    )
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}
    context = get_connection_context(connection_id)
    access_token = context.get("accessToken") or context.get("access_token")
    if not access_token:
        return {"success": False, "error": "Square access token not available."}

    caller_phone = context.get("caller") or phone_number
    if not caller_phone:
        return {"success": False, "error": "phone_number is required for customer creation."}

    lookup = await fetch_square_customer_by_phone(access_token, caller_phone)
    if lookup.get("success") and lookup.get("customer"):
        return {
            "success": True,
            "customer": lookup.get("customer"),
            "duplicate": True,
        }

    client = AsyncSquare(token=access_token, environment=_square_environment())
    return await create_square_customer(
        client,
        first_name=first_name,
        last_name=last_name,
        phone_number=caller_phone,
    )


async def create_square_booking(
    client: AsyncSquare,
    booking: Dict[str, Any],
) -> Dict[str, Any]:
    logger.debug("business_logic.create_square_booking called")
    response = await client.bookings.create(
        booking=booking,
        idempotency_key=str(uuid.uuid4()),
    )
    parsed = _parse_square_response(response)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}
    created = parsed.get("payload", {}).get("booking")
    return {"success": True, "booking": created}


def _availability_start_at(availability: Any) -> Optional[str]:
    logger.debug("business_logic._availability_start_at called (type=%s)", type(availability))
    if isinstance(availability, dict):
        return availability.get("start_at") or availability.get("startAt")
    for attr in ("start_at", "startAt"):
        value = getattr(availability, attr, None)
        if value:
            return value
    if hasattr(availability, "model_dump"):
        data = availability.model_dump()
        return data.get("start_at") or data.get("startAt")
    return None


def _resolve_location_timezone(context: Dict[str, Any]) -> Optional[str]:
    logger.debug("business_logic._resolve_location_timezone called")
    location = context.get("location") or {}
    timezone_name = location.get("timezone")
    return timezone_name


def _availability_duration_minutes(availability: Any) -> Optional[int]:
    logger.debug("business_logic._availability_duration_minutes called (type=%s)", type(availability))
    segments = None
    if isinstance(availability, dict):
        segments = availability.get("appointment_segments") or availability.get("appointmentSegments")
    else:
        segments = getattr(availability, "appointment_segments", None) or getattr(
            availability,
            "appointmentSegments",
            None,
        )
    if not segments and hasattr(availability, "model_dump"):
        data = availability.model_dump()
        segments = data.get("appointment_segments") or data.get("appointmentSegments")
    if not segments:
        return None
    total = 0
    for segment in segments:
        duration = None
        intermission = 0
        if isinstance(segment, dict):
            duration = segment.get("duration_minutes") or segment.get("durationMinutes")
            intermission = segment.get("intermission_minutes") or segment.get("intermissionMinutes") or 0
        else:
            duration = getattr(segment, "duration_minutes", None) or getattr(segment, "durationMinutes", None)
            intermission = getattr(segment, "intermission_minutes", None) or getattr(segment, "intermissionMinutes", None) or 0
        if duration:
            total += int(duration) + int(intermission)
    return total or None


def _availability_team_member_ids(availability: Any) -> list[str]:
    segments = None
    if isinstance(availability, dict):
        segments = availability.get("appointment_segments") or availability.get("appointmentSegments")
    else:
        segments = getattr(availability, "appointment_segments", None) or getattr(
            availability,
            "appointmentSegments",
            None,
        )
    if not segments and hasattr(availability, "model_dump"):
        data = availability.model_dump()
        segments = data.get("appointment_segments") or data.get("appointmentSegments")
    if not segments:
        return []

    team_member_ids: list[str] = []
    for segment in segments:
        member_id = None
        if isinstance(segment, dict):
            member_id = segment.get("team_member_id") or segment.get("teamMemberId")
        else:
            member_id = getattr(segment, "team_member_id", None) or getattr(segment, "teamMemberId", None)
        if member_id:
            team_member_ids.append(member_id)
    return team_member_ids


def _resolve_available_staff(context: Dict[str, Any], availabilities: list[Any]) -> list[Dict[str, Any]]:
    staff = context.get("staff") or []
    staff_map = {}
    for member in staff:
        member_id = member.get("id")
        if not member_id:
            continue
        display_name = member.get("display_name") or " ".join(
            part for part in [member.get("given_name"), member.get("family_name")] if part
        ).strip()
        staff_map[member_id] = display_name or member_id

    available_ids = set()
    for availability in availabilities:
        for member_id in _availability_team_member_ids(availability):
            available_ids.add(member_id)

    available_staff: list[Dict[str, Any]] = []
    for member_id in sorted(available_ids):
        available_staff.append(
            {
                "id": member_id,
                "display_name": staff_map.get(member_id, member_id),
            }
        )
    return available_staff


def _format_availability_response(availabilities: list[Any], tzinfo) -> Dict[str, Any]:
    logger.debug("business_logic._format_availability_response called (count=%d)", len(availabilities))
    slots: list[Dict[str, Any]] = []
    ranges: list[Dict[str, Any]] = []
    slot_ranges: list[tuple[datetime, datetime]] = []

    for availability in availabilities:
        start_at = _availability_start_at(availability)
        if not start_at:
            continue
        normalized_start = _normalize_iso(start_at)
        try:
            start_dt = datetime.fromisoformat(normalized_start)
        except ValueError:
            start_dt = None
        if start_dt and tzinfo:
            start_dt = start_dt.astimezone(tzinfo)
        duration_minutes = _availability_duration_minutes(availability)
        if start_dt and duration_minutes:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            slot_ranges.append((start_dt, end_dt))

        slots.append(
            {
                "start_at": start_dt.isoformat(timespec="seconds") if start_dt else start_at,
                "date": start_dt.date().isoformat() if start_dt else start_at.split("T")[0],
                "time": start_dt.time().strftime("%H:%M") if start_dt else start_at.split("T")[-1],
            }
        )

    slot_ranges.sort(key=lambda pair: pair[0])
    if slot_ranges:
        current_start, current_end = slot_ranges[0]
        for start_dt, end_dt in slot_ranges[1:]:
            if start_dt <= current_end:
                current_end = max(current_end, end_dt)
                continue
            if start_dt == current_end:
                current_end = end_dt
                continue
            ranges.append(
                {
                    "start_at": current_start.isoformat(timespec="seconds"),
                    "end_at": current_end.isoformat(timespec="seconds"),
                    "date": current_start.date().isoformat(),
                    "start_time": current_start.strftime("%H:%M"),
                    "end_time": current_end.strftime("%H:%M"),
                }
            )
            current_start, current_end = start_dt, end_dt
        ranges.append(
            {
                "start_at": current_start.isoformat(timespec="seconds"),
                "end_at": current_end.isoformat(timespec="seconds"),
                "date": current_start.date().isoformat(),
                "start_time": current_start.strftime("%H:%M"),
                "end_time": current_end.strftime("%H:%M"),
            }
        )

    if ranges and len(ranges) <= len(slots):
        return {"mode": "range", "ranges": ranges, "slots": []}
    return {"mode": "slots", "ranges": [], "slots": slots}


def _end_of_day(dt_value: datetime) -> datetime:
    logger.debug("business_logic._end_of_day called (value=%s)", dt_value)
    return dt_value.replace(hour=23, minute=59, second=59, microsecond=999000)


def _relative_range(name: str, now: datetime) -> tuple[datetime, datetime]:
    logger.debug("business_logic._relative_range called (name=%s now=%s)", name, now)
    key = name.upper()
    if key in {"TODAY", "NOW"}:
        start = _start_of_day(now)
        end = _end_of_day(now)
    elif key in {"TOMORROW", "TMRO", "TMRW"}:
        target = now + timedelta(days=1)
        start = _start_of_day(target)
        end = _end_of_day(target)
    elif key == "YESTERDAY":
        target = now - timedelta(days=1)
        start = _start_of_day(target)
        end = _end_of_day(target)
    elif key in {"THIS_WEEK", "CURRENT_WEEK"}:
        start = _start_of_day(now - timedelta(days=now.weekday()))
        end = _end_of_day(start + timedelta(days=6))
    elif key in {"NEXT_WEEK", "NEXO_WEEK"}:
        start = _start_of_day(now - timedelta(days=now.weekday()) + timedelta(days=7))
        end = _end_of_day(start + timedelta(days=6))
    elif key == "LAST_WEEK":
        start = _start_of_day(now - timedelta(days=now.weekday()) - timedelta(days=7))
        end = _end_of_day(start + timedelta(days=6))
    elif key in {"THIS_WEEKEND", "WEEKEND"}:
        days_until_sat = (5 - now.weekday()) % 7
        start = _start_of_day(now + timedelta(days=days_until_sat))
        end = _end_of_day(start + timedelta(days=1))
    elif key == "NEXT_WEEKEND":
        days_until_next_sat = (5 - now.weekday()) % 7 + 7
        start = _start_of_day(now + timedelta(days=days_until_next_sat))
        end = _end_of_day(start + timedelta(days=1))
    elif key in {"THIS_MONTH", "CURRENT_MONTH"}:
        start = _start_of_day(now.replace(day=1))
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = _end_of_day(next_month - timedelta(days=1))
    elif key == "NEXT_MONTH":
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        start = _start_of_day(next_month)
        next_next = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = _end_of_day(next_next - timedelta(days=1))
    elif key == "LAST_MONTH":
        this_month = now.replace(day=1)
        last_month_end = this_month - timedelta(days=1)
        start = _start_of_day(last_month_end.replace(day=1))
        end = _end_of_day(last_month_end)
    elif key == "NEXT_7_DAYS":
        start = _start_of_day(now)
        end = _end_of_day(now + timedelta(days=6))
    elif key == "NEXT_14_DAYS":
        start = _start_of_day(now)
        end = _end_of_day(now + timedelta(days=13))
    elif key == "NEXT_30_DAYS":
        start = _start_of_day(now)
        end = _end_of_day(now + timedelta(days=29))
    else:
        start = _start_of_day(now)
        end = _end_of_day(now)
    return start, end


_WEEKDAY_MAP = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def _resolve_weekday_range(value: str, now: datetime) -> Optional[tuple[datetime, datetime]]:
    text = value.strip().lower()
    modifier = None
    if text.startswith("next "):
        modifier = "next"
        text = text[5:].strip()
    elif text.startswith("this "):
        modifier = "this"
        text = text[5:].strip()

    weekday = _WEEKDAY_MAP.get(text)
    if weekday is None:
        return None

    days_ahead = (weekday - now.weekday() + 7) % 7
    if modifier == "next" and days_ahead == 0:
        days_ahead = 7
    target = now + timedelta(days=days_ahead)
    return _start_of_day(target), _end_of_day(target)


def _resolve_date_range(
    start_value: str,
    end_value: Optional[str],
    tzinfo,
) -> tuple[datetime, datetime]:
    logger.debug(
        "business_logic._resolve_date_range called (start=%s end=%s tz=%s)",
        start_value,
        end_value,
        tzinfo,
    )
    now = datetime.now(tzinfo) if tzinfo else datetime.now()
    if start_value and start_value.upper() in {
        "TODAY",
        "NOW",
        "TOMORROW",
        "TMRO",
        "TMRW",
        "YESTERDAY",
        "THIS_WEEK",
        "CURRENT_WEEK",
        "NEXT_WEEK",
        "NEXO_WEEK",
        "LAST_WEEK",
        "THIS_WEEKEND",
        "WEEKEND",
        "NEXT_WEEKEND",
        "THIS_MONTH",
        "CURRENT_MONTH",
        "NEXT_MONTH",
        "LAST_MONTH",
        "NEXT_7_DAYS",
        "NEXT_14_DAYS",
        "NEXT_30_DAYS",
    }:
        return _relative_range(start_value, now)

    weekday_range = _resolve_weekday_range(start_value, now)
    if weekday_range:
        return weekday_range

    start_dt = _parse_datetime(start_value)
    if tzinfo and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo)

    if end_value:
        end_dt = _parse_datetime(end_value)
        if tzinfo and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=tzinfo)
        return start_dt, end_dt

    if "T" not in start_value:
        return _start_of_day(start_dt), _end_of_day(start_dt)
    return start_dt, start_dt + timedelta(days=7)


async def get_customer(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    customer_id: Optional[str] = None,
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up a customer."""
    logger.debug(
        "business_logic.get_customer called (phone=%s email=%s customer_id=%s connection_id=%s)",
        phone,
        email,
        customer_id,
        connection_id,
    )
    if not any([phone, email, customer_id]) and connection_id:
        context = get_connection_context(connection_id)
        prefetched = context.get("prefetchedCustomer") or {}
        if isinstance(prefetched, dict):
            prefetched_customer = prefetched.get("customer")
            if prefetched_customer:
                return {"success": True, "customer": prefetched_customer, "new_customer": False}
            if prefetched.get("newCustomer") or prefetched.get("new_customer"):
                return {"success": False, "error": "Customer not found.", "new_customer": True}
        phone = context.get("caller")
    if not any([phone, email, customer_id]):
        return {"error": "phone, email, or customer_id is required"}

    if phone and connection_id:
        context = get_connection_context(connection_id)
        access_token = context.get("accessToken") or context.get("access_token")
        if access_token:
            normalized = normalize_phone_number(phone) or phone
            result = await fetch_square_customer_by_phone(access_token, normalized)
            if result.get("success"):
                return {"success": True, "customer": result.get("customer"), "new_customer": False}
            if result.get("new_customer"):
                return {"success": False, "error": "Customer not found.", "new_customer": True}

    return {
        "success": True,
        "customer": {
            "customer_id": customer_id or "CUST0001",
            "phone": phone or "+15551234567",
            "email": email or "customer@example.com",
            "name": "Alex Customer",
        },
        "new_customer": False,
    }


async def get_customer_appointments(customer_id: str) -> Dict[str, Any]:
    """Mock appointment history."""
    logger.debug("business_logic.get_customer_appointments called (customer_id=%s)", customer_id)
    now = datetime.now()
    return {
        "success": True,
        "appointments": [
            {
                "appointment_id": "APT0123",
                "service": "Consultation",
                "date": (now + timedelta(days=2)).isoformat(timespec="seconds"),
                "status": "confirmed",
            }
        ],
    }


async def get_customer_orders(customer_id: str) -> Dict[str, Any]:
    """Mock order history."""
    logger.debug("business_logic.get_customer_orders called (customer_id=%s)", customer_id)
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


async def schedule_appointment(customer_id: str, date: str, service: str) -> Dict[str, Any]:
    """Mock appointment scheduling."""
    logger.debug(
        "business_logic.schedule_appointment called (customer_id=%s date=%s service=%s)",
        customer_id,
        date,
        service,
    )
    _ = customer_id
    return {
        "success": True,
        "appointment": {
            "appointment_id": "APT0456",
            "date": date,
            "service": service,
            "status": "confirmed",
        },
    }


async def schedule_appointment_with_contact(
    connection_id: Optional[str],
    first_name: str,
    last_name: str,
    date: str,
    service: str,
    phone_number: Optional[str] = None,
    customer_id: Optional[str] = None,
    staff_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule an appointment, creating a customer if needed."""
    logger.debug(
        "business_logic.schedule_appointment_with_contact called (connection_id=%s date=%s service=%s phone=%s customer_id=%s staff_id=%s)",
        connection_id,
        date,
        service,
        phone_number,
        customer_id,
        staff_id,
    )
    caller_phone = None
    if connection_id:
        context = get_connection_context(connection_id)
        caller_phone = context.get("caller")
    if not caller_phone:
        caller_phone = phone_number

    if not connection_id:
        return {"success": False, "error": "connection_id is required"}

    context = get_connection_context(connection_id)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    if not access_token or not location_id:
        return {"success": False, "error": "Missing Square access token or location ID."}

    client = AsyncSquare(token=access_token, environment=_square_environment())
    timezone = _resolve_location_timezone(context)
    tzinfo = ZoneInfo(timezone) if timezone and ZoneInfo else None
    start_at = _normalize_booking_start_at(date, tzinfo)

    resolved_customer_id = customer_id
    if not resolved_customer_id and caller_phone:
        lookup = await fetch_square_customer_by_phone(access_token, caller_phone)
        if lookup.get("success") and lookup.get("customer"):
            resolved_customer_id = lookup["customer"].get("id")
        elif lookup.get("new_customer"):
            logger.info("Creating new Square customer for %s", caller_phone)
            if not caller_phone:
                return {"success": False, "error": "phone_number is required for customer creation."}
            created = await create_square_customer(
                client,
                first_name=first_name,
                last_name=last_name,
                phone_number=caller_phone,
            )
            if not created.get("success"):
                return {"success": False, "error": created.get("error")}
            resolved_customer_id = (created.get("customer") or {}).get("id")

    if not resolved_customer_id:
        return {"success": False, "error": "Customer not found and could not be created."}

    service_variation_id, duration_minutes, service_version = _match_service_variation(context, service)
    if not service_variation_id:
        return {"success": False, "error": "Service not available for booking."}

    appointment_segment = {
        "service_variation_id": service_variation_id,
    }
    if service_version:
        appointment_segment["service_variation_version"] = service_version
    if duration_minutes:
        appointment_segment["duration_minutes"] = duration_minutes
    if not staff_id:
        return {"success": False, "error": "staff_id is required for booking."}
    appointment_segment["team_member_id"] = staff_id

    booking_payload = {
        "start_at": start_at,
        "location_id": location_id,
        "customer_id": resolved_customer_id,
        "appointment_segments": [appointment_segment],
    }
    created_booking = await create_square_booking(client, booking_payload)
    if not created_booking.get("success"):
        return {"success": False, "error": created_booking.get("error")}

    booking = created_booking.get("booking") or {}
    return {
        "success": True,
        "appointment": {
            "appointment_id": booking.get("id"),
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": caller_phone,
            "customer_id": resolved_customer_id,
            "date": booking.get("start_at") or start_at,
            "service": service,
            "status": booking.get("status") or "confirmed",
        },
    }


async def forward_call_to_location(connection_id: Optional[str]) -> Dict[str, Any]:
    """Forward the active call to the business location phone number."""
    logger.debug("business_logic.forward_call_to_location called (connection_id=%s)", connection_id)
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}
    if not config.settings.twilio_auth_token:
        return {"success": False, "error": "Twilio auth token not configured."}

    context = get_connection_context(connection_id)
    account_sid = context.get("accountSid")
    call_sid = context.get("callSid")
    location = context.get("location") or {}
    location_phone = location.get("phone_number")
    if not account_sid or not call_sid:
        return {"success": False, "error": "Missing Twilio call identifiers."}
    if not location_phone:
        return {"success": False, "error": "Location phone number not available."}

    normalized = normalize_phone_number(location_phone) or location_phone
    client = TwilioClient(account_sid, config.settings.twilio_auth_token)
    try:
        client.calls(call_sid).update(
            twiml=f"<Response><Dial>{normalized}</Dial></Response>"
        )
    except Exception as exc:
        logger.error("Failed to forward call for %s: %s", connection_id, exc, exc_info=True)
        return {"success": False, "error": "Failed to forward call."}

    return {"success": True, "forwarded_to": normalized}


async def get_available_appointment_slots(
    start_date: str,
    end_date: Optional[str],
    connection_id: Optional[str] = None,
    staff_ids: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Fetch availability from Square search_availability."""
    logger.debug(
        "business_logic.get_available_appointment_slots called (start_date=%s end_date=%s connection_id=%s)",
        start_date,
        end_date,
        connection_id,
    )
    logger.debug(
        "Availability request received (connection_id=%s start_date=%s end_date=%s)",
        connection_id,
        start_date,
        end_date,
    )
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}

    context = get_connection_context(connection_id)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    logger.debug(
        "Availability context (location_id=%s token_present=%s)",
        location_id,
        bool(access_token),
    )
    if not access_token or not location_id:
        logger.warning(
            "Missing Square auth context for %s (locationId=%s, token=%s)",
            connection_id,
            location_id,
            bool(access_token),
        )
        return {"success": False, "error": "Missing Square access token or location ID."}

    client = AsyncSquare(token=access_token, environment=_square_environment())
    timezone = _resolve_location_timezone(context)
    tzinfo = ZoneInfo(timezone) if timezone and ZoneInfo else None
    start_at_local, end_at_local = _resolve_date_range(start_date, end_date, tzinfo)
    start_at_local, end_at_local = _ensure_minimum_range(start_at_local, end_at_local)
    start_at = _isoformat_utc(start_at_local)
    end_at = _isoformat_utc(end_at_local)
    logger.debug(
        "Availability range resolved (start=%s end=%s tz=%s start_local=%s end_local=%s)",
        start_at,
        end_at,
        timezone,
        start_at_local.isoformat(timespec="seconds"),
        end_at_local.isoformat(timespec="seconds"),
    )
    filter_payload = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
    }
    service_variation_id = _select_service_variation_id(context)
    if service_variation_id:
        filter_payload["segment_filters"] = [{"service_variation_id": service_variation_id}]
    if staff_ids:
        if "segment_filters" not in filter_payload:
            filter_payload["segment_filters"] = [{}]
        filter_payload["segment_filters"][0]["team_member_id_filter"] = {"any": staff_ids}

    logger.debug(
        "Square search_availability request (location_id=%s start_at=%s end_at=%s service_variation_id=%s)",
        location_id,
        start_at,
        end_at,
        service_variation_id,
    )
    response = await client.bookings.search_availability(query={"filter": filter_payload})
    parsed = _parse_square_response(response)
    if not parsed.get("success"):
        logger.error(
            "Square search_availability failed (location_id=%s error=%s)",
            location_id,
            parsed.get("error"),
        )
        return {"success": False, "error": parsed.get("error")}

    availabilities = parsed.get("payload", {}).get("availabilities") or []
    availability = _format_availability_response(availabilities, tzinfo)
    available_staff = _resolve_available_staff(context, availabilities)
    if staff_ids:
        staff_id_set = set(staff_ids)
        available_staff = [member for member in available_staff if member.get("id") in staff_id_set]
    logger.debug(
        "Availability formatted (mode=%s slots=%d ranges=%d)",
        availability.get("mode"),
        len(availability.get("slots", [])),
        len(availability.get("ranges", [])),
    )
    return {
        "success": True,
        "availability_mode": availability.get("mode"),
        "slots": availability.get("slots"),
        "ranges": availability.get("ranges"),
        "available_staff": available_staff,
    }


async def prefetch_customer_by_phone(
    phone_number: Optional[str],
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prefetch customer data based on caller phone."""
    logger.debug(
        "business_logic.prefetch_customer_by_phone called (phone=%s connection_id=%s)",
        phone_number,
        connection_id,
    )
    if not phone_number:
        return {"success": False, "error": "phone_number is required"}
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}

    context = get_connection_context(connection_id)
    access_token = context.get("accessToken") or context.get("access_token")
    if not access_token:
        return {"success": False, "error": "Square access token not available."}

    normalized = normalize_phone_number(phone_number) or phone_number
    result = await fetch_square_customer_by_phone(access_token, normalized)
    return {
        "success": result.get("success", False),
        "customer": result.get("customer"),
        "newCustomer": result.get("new_customer", False),
        "error": result.get("error"),
    }


async def prepare_farewell_message(websocket, farewell_type: str, message: str = "Alright, have a nice day.") -> Dict[str, Any]:
    """Mock farewell handler."""
    logger.debug("business_logic.prepare_farewell_message called (farewell_type=%s)", farewell_type)
    _ = websocket
    return {
        "success": True,
        "farewell_type": farewell_type,
        "message": message,
    }
