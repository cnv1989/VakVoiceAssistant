"""
Business logic for agent function calls.
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional

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

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

logger = logging.getLogger(__name__)


def _square_environment():
    env_name = config.settings.square_environment
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if env_name == "sandbox" else SquareEnvironment.PRODUCTION
    return "sandbox" if env_name == "sandbox" else "production"


def _parse_square_response(response: Any) -> Dict[str, Any]:
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
    services = context.get("services") or []
    for item in services:
        item_data = item.get("item_data") or {}
        for variation in item_data.get("variations") or []:
            variation_id = variation.get("id")
            if variation_id:
                return variation_id
    return None


def _normalize_iso(value: str) -> str:
    return value.replace("Z", "+00:00")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(_normalize_iso(value))


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _start_of_day(dt_value: datetime) -> datetime:
    return dt_value.replace(hour=0, minute=0, second=0, microsecond=0)


def _ensure_minimum_range(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    if end_at <= start_at or end_at - start_at < timedelta(days=1):
        end_at = start_at + timedelta(days=1)
    if end_at - start_at > timedelta(days=32):
        end_at = start_at + timedelta(days=32)
    return start_at, end_at


def _availability_start_at(availability: Any) -> Optional[str]:
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
    location = context.get("location") or {}
    timezone_name = location.get("timezone")
    return timezone_name


def _availability_duration_minutes(availability: Any) -> Optional[int]:
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


def _format_availability_response(availabilities: list[Any], tzinfo) -> Dict[str, Any]:
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
    return dt_value.replace(hour=23, minute=59, second=59, microsecond=999000)


def _relative_range(name: str, now: datetime) -> tuple[datetime, datetime]:
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


def _resolve_date_range(
    start_value: str,
    end_value: Optional[str],
    tzinfo,
) -> tuple[datetime, datetime]:
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
) -> Dict[str, Any]:
    """Mock appointment scheduling using caller phone when available."""
    caller_phone = phone_number
    if not caller_phone and connection_id:
        context = get_connection_context(connection_id)
        caller_phone = context.get("caller")
    return {
        "success": True,
        "appointment": {
            "appointment_id": "APT0456",
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": caller_phone,
            "date": date,
            "service": service,
            "status": "confirmed",
        },
    }


async def get_available_appointment_slots(
    start_date: str,
    end_date: Optional[str],
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch availability from Square search_availability."""
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
    }


async def prefetch_customer_by_phone(
    phone_number: Optional[str],
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prefetch customer data based on caller phone."""
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
    _ = websocket
    return {
        "success": True,
        "farewell_type": farewell_type,
        "message": message,
    }
