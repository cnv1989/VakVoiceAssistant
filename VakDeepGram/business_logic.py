"""
Business logic for agent function calls.
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional
import uuid

from square import AsyncSquare
from square.core.api_error import ApiError as SquareApiError

import config
from connection_store import (
    fetch_square_customer_by_phone,
    get_connection_context,
)
from utils.phone import normalize_phone_number
from utils import setmore_api
from utils import booking_helpers
from utils.square_helpers import (
    get_square_environment as _square_environment,
    parse_square_response as _parse_square_response,
    extract_square_cursor as _extract_square_cursor,
)
from twilio.rest import Client as TwilioClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

logger = logging.getLogger(__name__)


def _provider_from_context(context: Dict[str, Any]) -> str:
    return (context.get("provider") or "square").lower()


def _setmore_match_service(context: Dict[str, Any], service_name: str) -> Optional[Dict[str, Any]]:
    if not service_name:
        return None
    target = service_name.strip().lower()
    for service in context.get("services") or []:
        name = (service.get("name") or "").strip().lower()
        if name == target:
            return service
    for service in context.get("services") or []:
        name = (service.get("name") or "").strip().lower()
        if target in name:
            return service
    return None


def _setmore_resolve_staff_key(context: Dict[str, Any], staff_ids: Optional[list[str]]) -> Optional[str]:
    staff_list = context.get("staff") or []
    if staff_ids:
        requested = [value.lower() for value in staff_ids if isinstance(value, str)]
        for staff in staff_list:
            staff_id = (staff.get("id") or "").lower()
            display_name = (staff.get("display_name") or "").lower()
            if staff_id in requested or display_name in requested:
                return staff.get("id")
    if staff_list:
        return staff_list[0].get("id")
    return None


def _setmore_format_date(dt_value: datetime) -> str:
    return dt_value.strftime("%d/%m/%Y")


def _setmore_slot_to_iso(date_value: datetime, slot: str, tzinfo) -> Optional[str]:
    try:
        if isinstance(slot, str):
            parts = slot.replace(":", ".").split(".")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            return None
        start_dt = date_value.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tzinfo and start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tzinfo)
        return start_dt.isoformat(timespec="seconds")
    except Exception:
        return None


def _setmore_phone_fields(phone_number: Optional[str]) -> Dict[str, Optional[str]]:
    if not phone_number:
        return {"country_code": None, "cell_phone": None}
    normalized = normalize_phone_number(phone_number) or phone_number
    if normalized.startswith("+") and len(normalized) > 2:
        # Best-effort split: country code is first 2-3 chars
        country_code = normalized[:2] if normalized.startswith("+1") else normalized[:3]
        return {"country_code": country_code, "cell_phone": normalized}
    return {"country_code": None, "cell_phone": normalized}


def _normalize_setmore_booking_url(raw: str) -> str:
    """Ensure the booking page URL is a full https://...setmore.com URL.

    Accepts:
      - Full URL: https://mybiz.setmore.com  →  as-is
      - Missing scheme: mybiz.setmore.com    →  https://mybiz.setmore.com
      - Bare slug: mybiz                     →  https://mybiz.setmore.com
    """
    import re
    val = raw.strip().rstrip("/")
    if not val:
        return val
    if re.match(r"^https?://", val, re.IGNORECASE):
        return val
    if ".setmore.com" in val.lower():
        return f"https://{val}"
    return f"https://{val}.setmore.com"


def build_setmore_booking_url(
    booking_page_url: str,
    service_key: Optional[str] = None,
    staff_key: Optional[str] = None,
    start_dt: Optional[datetime] = None,
    customer_key: Optional[str] = None,
) -> str:
    """Build a Setmore booking URL with prefilled query parameters.

    Setmore booking pages accept these query parameters:
        step       – "payment" to skip straight to confirmation
        products   – service UUID
        type       – "service"
        staff      – staff UUID
        slot       – appointment start time as Unix-epoch milliseconds
        customer   – customer UUID

    Example:
        https://mybiz.setmore.com/book?step=payment&products=<svc>&type=service
            &staff=<staff>&slot=<epoch_ms>&customer=<cust>
    """
    from urllib.parse import urlparse, urlencode

    normalized = _normalize_setmore_booking_url(booking_page_url)

    # Ensure the base URL ends with /book (or similar)
    parsed = urlparse(normalized.rstrip("/"))
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    # If the stored URL doesn't already end in /book, append it
    if not path.endswith("/book"):
        path = f"{path}/book" if path else "/book"

    params: Dict[str, str] = {"step": "payment", "type": "service"}
    if service_key:
        params["products"] = service_key
    if staff_key:
        params["staff"] = staff_key
    if start_dt:
        # Convert to epoch milliseconds (Setmore expects millis)
        epoch_ms = int(start_dt.timestamp() * 1000)
        params["slot"] = str(epoch_ms)
    if customer_key:
        params["customer"] = customer_key

    return f"{base}{path}?{urlencode(params)}"


def send_booking_link_sms(
    from_number: str,
    to_number: str,
    booking_page_url: str,
    service_name: str,
    staff_name: Optional[str],
    start_dt: datetime,
    customer_first_name: Optional[str] = None,
    service_key: Optional[str] = None,
    staff_key: Optional[str] = None,
    customer_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Send an SMS with a prefilled Setmore booking link.

    When service_key, staff_key, slot time, and/or customer_key are provided
    the booking URL is constructed with query parameters so the customer lands
    on the confirmation page with everything already selected.
    """
    twilio_account_sid = config.settings.twilio_account_sid
    twilio_auth_token = config.settings.twilio_auth_token
    if not twilio_account_sid or not twilio_auth_token:
        logger.error("Twilio credentials not configured for booking link SMS")
        return {"success": False, "error": "Twilio credentials not configured."}

    # Build prefilled URL when we have IDs; fall back to base URL
    if service_key or staff_key or customer_key:
        prefilled_url = build_setmore_booking_url(
            booking_page_url,
            service_key=service_key,
            staff_key=staff_key,
            start_dt=start_dt,
            customer_key=customer_key,
        )
    else:
        prefilled_url = booking_page_url

    # Format date/time for the human-readable portion
    date_str = start_dt.strftime("%A, %B %d, %Y")
    time_str = start_dt.strftime("%I:%M %p").lstrip("0")

    greeting = f"Hi {customer_first_name}! " if customer_first_name else ""
    staff_line = f"\nStaff: {staff_name}" if staff_name else ""
    body = (
        f"{greeting}Here are your appointment details:\n"
        f"\nService: {service_name}"
        f"{staff_line}"
        f"\nDate: {date_str}"
        f"\nTime: {time_str}"
        f"\n\nComplete your booking here:\n{prefilled_url}"
    )

    try:
        client = TwilioClient(twilio_account_sid, twilio_auth_token)
        sms_message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number,
        )
        logger.info(
            "Sent booking link SMS: sid=%s from=%s to=%s url=%s",
            sms_message.sid,
            from_number,
            to_number,
            prefilled_url,
        )
        return {
            "success": True,
            "sms_sid": sms_message.sid,
            "message_body": body,
            "booking_url": prefilled_url,
        }
    except Exception as exc:
        logger.error("Failed to send booking link SMS: %s", exc, exc_info=True)
        return {"success": False, "error": f"Failed to send SMS: {exc}"}


def _select_team_member_id(context: Dict[str, Any]) -> Optional[str]:
    logger.info("business_logic._select_team_member_id called")
    staff = context.get("staff") or []
    for member in staff:
        if member.get("status") == "ACTIVE" and member.get("id"):
            return member.get("id")
    for member in staff:
        if member.get("id"):
            return member.get("id")
    return None


def _normalize_iso(value: str) -> str:
    logger.info("business_logic._normalize_iso called (value=%s)", value)
    return value.replace("Z", "+00:00")


def _parse_datetime(value: str) -> datetime:
    logger.info("business_logic._parse_datetime called (value=%s)", value)
    return datetime.fromisoformat(_normalize_iso(value))


def _isoformat_utc(value: datetime) -> str:
    logger.info("business_logic._isoformat_utc called (value=%s)", value)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _start_of_day(dt_value: datetime) -> datetime:
    logger.info("business_logic._start_of_day called (value=%s)", dt_value)
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
    logger.info("business_logic._normalize_booking_start_at called (value=%s tz=%s)", value, tzinfo)
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
    logger.info("business_logic.create_square_customer called (phone=%s)", normalized_phone)
    if not normalized_phone:
        return {"success": False, "error": "phone_number must be a valid E.164 number."}
    kwargs = {
        "idempotency_key": str(uuid.uuid4()),
        "given_name": first_name,
        "family_name": last_name,
    }
    kwargs["phone_number"] = normalized_phone
    try:
        response = await client.customers.create(**kwargs)
    except SquareApiError as exc:
        return {"success": False, "error": exc.body or str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
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
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    if not access_token:
        return {"success": False, "error": "Access token not available."}

    caller_phone = context.get("caller") or phone_number
    if not caller_phone:
        return {"success": False, "error": "phone_number is required for customer creation."}

    if provider == "setmore":
        phone_fields = _setmore_phone_fields(caller_phone)
        payload = {
            "first_name": first_name,
            "last_name": last_name,
        }
        if phone_fields.get("country_code"):
            payload["country_code"] = phone_fields["country_code"]
        if phone_fields.get("cell_phone"):
            payload["cell_phone"] = phone_fields["cell_phone"]
        created = await setmore_api.create_customer(access_token, payload)
        if not created.get("success"):
            return {"success": False, "error": created.get("error")}
        return {"success": True, "customer": created.get("customer")}

    lookup = await fetch_square_customer_by_phone(access_token, caller_phone)
    if lookup.get("success") and lookup.get("customer"):
        return {
            "success": True,
            "customer": lookup.get("customer"),
            "duplicate": True,
            "message": "Customer already exists. Confirm before using existing record.",
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
    logger.info("business_logic.create_square_booking called")
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
    logger.info("business_logic._availability_start_at called (type=%s)", type(availability))
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
    logger.info("business_logic._resolve_location_timezone called")
    location = context.get("location") or {}
    timezone_name = location.get("timezone") or context.get("timezone")
    return timezone_name


def _availability_duration_minutes(availability: Any) -> Optional[int]:
    logger.info("business_logic._availability_duration_minutes called (type=%s)", type(availability))
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


def _availability_start_dt(availability: Any, tzinfo) -> Optional[datetime]:
    start_at = _availability_start_at(availability)
    if not start_at:
        return None
    normalized_start = _normalize_iso(start_at)
    try:
        start_dt = datetime.fromisoformat(normalized_start)
    except ValueError:
        return None
    if tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    return start_dt


def _availability_supports_start(
    availability: Any,
    target_start: datetime,
    duration_minutes: Optional[int],
    tzinfo,
    tolerance_minutes: int,
) -> bool:
    start_dt = _availability_start_dt(availability, tzinfo)
    if not start_dt:
        return False
    duration = _availability_duration_minutes(availability) or duration_minutes
    if duration:
        end_dt = start_dt + timedelta(minutes=duration)
        requested_end = target_start + timedelta(minutes=duration)
        return start_dt <= target_start <= end_dt and requested_end <= end_dt
    delta = abs((start_dt - target_start).total_seconds())
    return delta <= tolerance_minutes * 60


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


def _resolve_staff_ids(context: Dict[str, Any], requested: list[Any]) -> tuple[list[str], list[str]]:
    staff = context.get("staff") or []
    if not requested:
        return [], []
    staff_by_id = {}
    staff_by_name = {}
    for member in staff:
        member_id = member.get("id")
        if not member_id:
            continue
        display_name = member.get("display_name") or " ".join(
            part for part in [member.get("given_name"), member.get("family_name")] if part
        ).strip()
        if display_name:
            staff_by_name[display_name.lower()] = member_id
        staff_by_id[member_id] = member_id

    resolved: list[str] = []
    unmatched: list[str] = []
    for value in requested:
        if not value:
            continue
        candidate = None
        if isinstance(value, dict):
            candidate = value.get("id") or value.get("display_name")
        elif isinstance(value, str):
            candidate = value
        if not candidate:
            continue
        candidate = candidate.strip()
        if candidate in staff_by_id:
            resolved.append(candidate)
            continue
        staff_id = staff_by_name.get(candidate.lower())
        if staff_id:
            resolved.append(staff_id)
            continue
        unmatched.append(candidate)
    return resolved, unmatched


def _staff_display_name(context: Dict[str, Any], staff_id: Optional[str]) -> Optional[str]:
    if not staff_id:
        return None
    for member in context.get("staff") or []:
        if member.get("id") == staff_id:
            display_name = member.get("display_name") or " ".join(
                part for part in [member.get("given_name"), member.get("family_name")] if part
            ).strip()
            return display_name or staff_id
    return staff_id


def _availability_window_minutes(
    service_name: Optional[str],
    duration_minutes: Optional[int],
) -> int:
    mapping = config.settings.booking_availability_window_by_service or {}
    if service_name and mapping:
        normalized = service_name.strip().lower()
        for key in sorted(mapping.keys(), key=len, reverse=True):
            if key.lower() in normalized:
                return int(mapping[key])
    if duration_minutes:
        return int(duration_minutes)
    return int(config.settings.booking_availability_window_minutes or 30)


def _format_availability_response(availabilities: list[Any], tzinfo) -> Dict[str, Any]:
    logger.info("business_logic._format_availability_response called (count=%d)", len(availabilities))
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
    logger.info("business_logic._end_of_day called (value=%s)", dt_value)
    return dt_value.replace(hour=23, minute=59, second=59, microsecond=999000)


def _booking_segments(booking: Any) -> list[Dict[str, Any]]:
    if isinstance(booking, dict):
        return booking.get("appointment_segments") or booking.get("appointmentSegments") or []
    segments = getattr(booking, "appointment_segments", None) or getattr(
        booking,
        "appointmentSegments",
        None,
    )
    if segments:
        return segments
    if hasattr(booking, "model_dump"):
        data = booking.model_dump()
        return data.get("appointment_segments") or data.get("appointmentSegments") or []
    return []


def _booking_version(booking: Any) -> Optional[int]:
    if isinstance(booking, dict):
        return booking.get("version")
    version = getattr(booking, "version", None)
    if version is not None:
        return version
    if hasattr(booking, "model_dump"):
        return booking.model_dump().get("version")
    return None


def _extract_booking_segment_details(booking: Any) -> Dict[str, Any]:
    segments = _booking_segments(booking)
    if not segments:
        return {}
    segment = segments[0]
    if isinstance(segment, dict):
        return {
            "service_variation_id": segment.get("service_variation_id") or segment.get("serviceVariationId"),
            "service_variation_version": segment.get("service_variation_version") or segment.get("serviceVariationVersion"),
            "team_member_id": segment.get("team_member_id") or segment.get("teamMemberId"),
            "duration_minutes": segment.get("duration_minutes") or segment.get("durationMinutes"),
        }
    return {
        "service_variation_id": getattr(segment, "service_variation_id", None) or getattr(segment, "serviceVariationId", None),
        "service_variation_version": getattr(segment, "service_variation_version", None) or getattr(segment, "serviceVariationVersion", None),
        "team_member_id": getattr(segment, "team_member_id", None) or getattr(segment, "teamMemberId", None),
        "duration_minutes": getattr(segment, "duration_minutes", None) or getattr(segment, "durationMinutes", None),
    }


def _relative_range(name: str, now: datetime) -> tuple[datetime, datetime]:
    logger.info("business_logic._relative_range called (name=%s now=%s)", name, now)
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
    first_name: Optional[str] = None,
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
    if not any([phone, email, customer_id, first_name]) and connection_id:
        context = get_connection_context(connection_id)
        context_customer = context.get("customer")
        if context_customer:
            return {"success": True, "customer": context_customer, "new_customer": False}
        phone = context.get("caller")
    if not any([phone, email, customer_id, first_name]):
        return {"error": "phone, email, or customer_id is required"}

    if connection_id:
        context = get_connection_context(connection_id)
        provider = _provider_from_context(context)
        access_token = context.get("accessToken") or context.get("access_token")
        if provider == "setmore" and access_token:
            if not first_name:
                return {"success": False, "error": "first_name is required for Setmore customer lookup."}
            normalized_phone = normalize_phone_number(phone) if phone else None
            result = await setmore_api.fetch_customer(
                access_token,
                first_name=first_name,
                phone=normalized_phone,
                email=email,
            )
            if result.get("success"):
                customers = result.get("customers") or []
                if customers:
                    return {"success": True, "customer": customers[0], "new_customer": False}
                return {"success": False, "error": "Customer not found.", "new_customer": True}
            return {"success": False, "error": result.get("error")}
        if phone and access_token:
            normalized = normalize_phone_number(phone) or phone
            result = await fetch_square_customer_by_phone(access_token, normalized)
            if result.get("success"):
                return {"success": True, "customer": result.get("customer"), "new_customer": False}
            if result.get("new_customer"):
                return {"success": False, "error": "Customer not found.", "new_customer": True}

    return {"success": False, "error": "Customer not found."}


async def get_customer_appointments(
    customer_id: str,
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get appointment history from Square for a customer."""
    logger.debug(
        "business_logic.get_customer_appointments called (customer_id=%s connection_id=%s)",
        customer_id,
        connection_id,
    )
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}
    context = get_connection_context(connection_id)
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    if not access_token:
        return {"success": False, "error": "Missing access token."}

    timezone_name = _resolve_location_timezone(context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    now = datetime.now(tzinfo) if tzinfo else datetime.now()

    if provider == "setmore":
        start_local = now - timedelta(days=1)
        end_local = now + timedelta(days=90)
        start_date = start_local.strftime("%d-%m-%Y")
        end_date = end_local.strftime("%d-%m-%Y")
        result = await setmore_api.fetch_appointments(
            access_token,
            start_date=start_date,
            end_date=end_date,
            customer_details=True,
        )
        if not result.get("success"):
            return {"success": False, "error": result.get("error")}
        appointments = result.get("appointments") or []
        if customer_id:
            appointments = [
                appt for appt in appointments if appt.get("customer_key") == customer_id
            ]
        formatted = []
        for appt in appointments:
            start_at = appt.get("start_time")
            start_local = None
            if start_at and tzinfo:
                try:
                    start_local = datetime.fromisoformat(_normalize_iso(start_at)).astimezone(tzinfo)
                except ValueError:
                    start_local = None
            formatted.append(
                {
                    "appointment_id": appt.get("key"),
                    "status": appt.get("status") or "scheduled",
                    "start_at": start_at,
                    "start_at_local": start_local.isoformat(timespec="seconds") if start_local else None,
                    "service_id": appt.get("service_key"),
                    "staff_id": appt.get("staff_key"),
                    "customer_id": appt.get("customer_key"),
                }
            )
        return {"success": True, "appointments": formatted}

    location_id = context.get("locationId")
    if not location_id:
        return {"success": False, "error": "Missing Square location ID."}

    client = AsyncSquare(token=access_token, environment=_square_environment())
    start_at_min = _isoformat_utc(now - timedelta(days=1))
    end_at_max = _isoformat_utc(now + timedelta(days=90))
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
        if hasattr(response, "__aiter__"):
            async for booking in response:
                appointments.append(booking)
            cursor = _extract_square_cursor(response)
        else:
            parsed = _parse_square_response(response)
            if not parsed.get("success"):
                return {"success": False, "error": parsed.get("error")}
            payload = parsed.get("payload", {})
            appointments.extend(payload.get("bookings") or [])
            cursor = payload.get("cursor")
        if not cursor:
            break

    formatted: list[Dict[str, Any]] = []
    for booking in appointments:
        if hasattr(booking, "model_dump"):
            booking = booking.model_dump()
        start_at = booking.get("start_at") or booking.get("startAt")
        start_local = None
        if start_at and tzinfo:
            try:
                start_local = datetime.fromisoformat(_normalize_iso(start_at)).astimezone(tzinfo)
            except ValueError:
                start_local = None
        segment_details = _extract_booking_segment_details(booking)
        formatted.append(
            {
                "appointment_id": booking.get("id"),
                "status": booking.get("status"),
                "start_at": start_at,
                "start_at_local": start_local.isoformat(timespec="seconds") if start_local else None,
                "service_variation_id": segment_details.get("service_variation_id"),
                "staff_id": segment_details.get("team_member_id"),
                "location_id": booking.get("location_id") or booking.get("locationId"),
            }
        )

    return {"success": True, "appointments": formatted}


async def get_customer_orders(customer_id: str) -> Dict[str, Any]:
    """Mock order history."""
    logger.info("business_logic.get_customer_orders called (customer_id=%s)", customer_id)
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
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    if not access_token:
        return {"success": False, "error": "Missing access token."}

    if provider == "setmore":
        timezone_name = _resolve_location_timezone(context)
        tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
        start_dt = _parse_datetime(date)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
        elif tzinfo:
            start_dt = start_dt.astimezone(tzinfo)

        service_item = _setmore_match_service(context, service)
        if not service_item:
            suggestions = [item.get("name") for item in context.get("services") or [] if item.get("name")]
            response = {"success": False, "error": "Service not available for booking."}
            if suggestions:
                response["suggested_services"] = suggestions[:5]
            return response

        service_key = service_item.get("id")
        if not service_key:
            return {"success": False, "error": "Service key not found."}

        # Ensure customer exists in Setmore so their info is prefilled
        resolved_customer_id = customer_id
        if not resolved_customer_id:
            phone_fields = _setmore_phone_fields(caller_phone)
            payload = {
                "first_name": first_name,
                "last_name": last_name,
            }
            if phone_fields.get("country_code"):
                payload["country_code"] = phone_fields["country_code"]
            if phone_fields.get("cell_phone"):
                payload["cell_phone"] = phone_fields["cell_phone"]
            created = await setmore_api.create_customer(access_token, payload)
            if not created.get("success"):
                return {"success": False, "error": created.get("error")}
            resolved_customer_id = (created.get("customer") or {}).get("key")

        resolved_staff_id = staff_id or _setmore_resolve_staff_key(context, [staff_id] if staff_id else [])
        staff_name = _staff_display_name(context, resolved_staff_id)
        service_name = service_item.get("name") or service

        # Send booking link via SMS instead of creating the appointment directly
        booking_page_url = context.get("bookingPageUrl") or context.get("booking_page_url")
        if not booking_page_url:
            return {"success": False, "error": "Booking page URL not configured for this business."}

        to_number = normalize_phone_number(caller_phone) if caller_phone else None
        from_number = context.get("businessNumber")
        if not to_number:
            return {"success": False, "error": "Customer phone number is required to send the booking link."}
        if not from_number:
            return {"success": False, "error": "Business phone number not available for sending SMS."}

        sms_result = send_booking_link_sms(
            from_number=from_number,
            to_number=to_number,
            booking_page_url=booking_page_url,
            service_name=service_name,
            staff_name=staff_name,
            start_dt=start_dt,
            customer_first_name=first_name,
            service_key=service_key,
            staff_key=resolved_staff_id,
            customer_key=resolved_customer_id,
        )
        if not sms_result.get("success"):
            return {"success": False, "error": sms_result.get("error")}

        prefilled_url = sms_result.get("booking_url") or booking_page_url
        return {
            "success": True,
            "booking_link_sent": True,
            "booking_url": prefilled_url,
            "appointment_details": {
                "date": start_dt.isoformat(),
                "service": service_name,
                "service_key": service_key,
                "staff_name": staff_name,
                "staff_key": resolved_staff_id,
                "customer_id": resolved_customer_id,
                "customer_phone": to_number,
            },
            "message": f"Booking link with prefilled details has been sent to {to_number} via text message.",
        }

    if not location_id:
        return {"success": False, "error": "Missing Square access token or location ID."}

    client = AsyncSquare(token=access_token, environment=_square_environment())
    timezone = _resolve_location_timezone(context)
    tzinfo = ZoneInfo(timezone) if timezone and ZoneInfo else None
    start_dt = _parse_datetime(date)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    effective_tzinfo = tzinfo or start_dt.tzinfo
    start_at = _isoformat_utc(start_dt)

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

    service_variation_id, duration_minutes, service_version = booking_helpers.match_service_variation(
        context,
        service,
    )
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    tolerance_minutes = _availability_window_minutes(service, duration_minutes)
    availability_start = start_dt - timedelta(minutes=tolerance_minutes)
    availability_end = start_dt + timedelta(minutes=tolerance_minutes + (duration_minutes or 0))
    availability_filter = {
        "start_at_range": {
            "start_at": _isoformat_utc(availability_start),
            "end_at": _isoformat_utc(availability_end),
        },
        "location_id": location_id,
    }
    availability_filter["segment_filters"] = [{"service_variation_id": service_variation_id}]
    availability_response = await client.bookings.search_availability(
        query={"filter": availability_filter}
    )
    availability_parsed = _parse_square_response(availability_response)
    if not availability_parsed.get("success"):
        return {"success": False, "error": availability_parsed.get("error")}

    availabilities = availability_parsed.get("payload", {}).get("availabilities") or []
    matching_availabilities = [
        availability
        for availability in availabilities
        if _availability_supports_start(
            availability,
            start_dt,
            duration_minutes,
            effective_tzinfo,
            tolerance_minutes,
        )
    ]
    available_staff_ids: list[str] = []
    for availability in matching_availabilities:
        available_staff_ids.extend(_availability_team_member_ids(availability))
    available_staff_id_set = {member_id for member_id in available_staff_ids if member_id}

    if staff_id:
        if staff_id not in available_staff_id_set:
            return {
                "success": False,
                "error": "Selected staff is not available around the requested time.",
            }
    else:
        for member in context.get("staff") or []:
            member_id = member.get("id")
            if member_id in available_staff_id_set and member.get("status") == "ACTIVE":
                staff_id = member_id
                break
        if not staff_id and available_staff_id_set:
            staff_id = sorted(available_staff_id_set)[0]
        if not staff_id:
            return {"success": False, "error": "No staff availability around the requested time."}

    staff_name = _staff_display_name(context, staff_id)
    appointment_segment = {
        "service_variation_id": service_variation_id,
    }
    if service_version:
        appointment_segment["service_variation_version"] = service_version
    if duration_minutes:
        appointment_segment["duration_minutes"] = duration_minutes
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
            "staff_id": staff_id,
            "staff_name": staff_name,
            "status": booking.get("status") or "confirmed",
        },
    }


async def update_appointment(
    connection_id: str,
    booking_id: str,
    date: str,
    service: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Reschedule an existing appointment."""
    logger.debug(
        "business_logic.update_appointment called (connection_id=%s booking_id=%s date=%s service=%s staff_id=%s)",
        connection_id,
        booking_id,
        date,
        service,
        staff_id,
    )
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}
    if not booking_id:
        return {"success": False, "error": "booking_id is required"}

    context = get_connection_context(connection_id)
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    if not access_token:
        return {"success": False, "error": "Missing access token."}
    if provider == "setmore":
        return {"success": False, "error": "Setmore appointment updates are not supported by the API."}
    if not location_id:
        return {"success": False, "error": "Missing Square access token or location ID."}

    client = AsyncSquare(token=access_token, environment=_square_environment())
    booking_response = await client.bookings.retrieve(booking_id=booking_id)
    booking_parsed = _parse_square_response(booking_response)
    if not booking_parsed.get("success"):
        return {"success": False, "error": booking_parsed.get("error")}
    booking = booking_parsed.get("payload", {}).get("booking") or {}
    if hasattr(booking, "model_dump"):
        booking = booking.model_dump()
    version = _booking_version(booking)
    if version is None:
        return {"success": False, "error": "Booking version not available."}

    segment_details = _extract_booking_segment_details(booking)
    if staff_name and not staff_id:
        resolved_staff_ids, unmatched_staff = _resolve_staff_ids(context, [staff_name])
        if unmatched_staff or not resolved_staff_ids:
            return {
                "success": False,
                "error": "Requested staff not found. Please confirm the staff member name.",
                "unmatched_staff": unmatched_staff,
            }
        staff_id = resolved_staff_ids[0]
    if not staff_id:
        staff_id = segment_details.get("team_member_id")
    if not staff_id:
        return {"success": False, "error": "staff_id is required for booking update."}

    if service:
        service_variation_id, duration_minutes, service_version = booking_helpers.match_service_variation(
            context,
            service,
        )
    else:
        service_variation_id = segment_details.get("service_variation_id")
        duration_minutes = segment_details.get("duration_minutes")
        service_version = segment_details.get("service_variation_version")
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    timezone_name = _resolve_location_timezone(context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    start_dt = _parse_datetime(date)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    effective_tzinfo = tzinfo or start_dt.tzinfo
    start_at = _isoformat_utc(start_dt)

    tolerance_minutes = _availability_window_minutes(service, duration_minutes)
    availability_start = start_dt - timedelta(minutes=tolerance_minutes)
    availability_end = start_dt + timedelta(minutes=tolerance_minutes + (duration_minutes or 0))
    availability_filter = {
        "start_at_range": {
            "start_at": _isoformat_utc(availability_start),
            "end_at": _isoformat_utc(availability_end),
        },
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": service_variation_id}],
    }
    availability_filter["segment_filters"][0]["team_member_id_filter"] = {"any": [staff_id]}
    availability_response = await client.bookings.search_availability(
        query={"filter": availability_filter}
    )
    availability_parsed = _parse_square_response(availability_response)
    if not availability_parsed.get("success"):
        return {"success": False, "error": availability_parsed.get("error")}

    availabilities = availability_parsed.get("payload", {}).get("availabilities") or []
    matching_availabilities = [
        availability
        for availability in availabilities
        if _availability_supports_start(
            availability,
            start_dt,
            duration_minutes,
            effective_tzinfo,
            tolerance_minutes,
        )
    ]
    available_staff_ids: list[str] = []
    for availability in matching_availabilities:
        available_staff_ids.extend(_availability_team_member_ids(availability))
    available_staff_id_set = {member_id for member_id in available_staff_ids if member_id}
    if staff_id not in available_staff_id_set:
        return {
            "success": False,
            "error": "Selected staff is not available around the requested time.",
        }

    appointment_segment = {
        "service_variation_id": service_variation_id,
        "team_member_id": staff_id,
    }
    if service_version:
        appointment_segment["service_variation_version"] = service_version
    if duration_minutes:
        appointment_segment["duration_minutes"] = duration_minutes

    update_payload = {
        "id": booking_id,
        "version": version,
        "start_at": start_at,
        "location_id": location_id,
        "appointment_segments": [appointment_segment],
    }
    customer_id = booking.get("customer_id") or booking.get("customerId")
    if customer_id:
        update_payload["customer_id"] = customer_id

    update_response = await client.bookings.update(
        booking_id=booking_id,
        booking=update_payload,
    )
    update_parsed = _parse_square_response(update_response)
    if not update_parsed.get("success"):
        return {"success": False, "error": update_parsed.get("error")}
    updated_booking = update_parsed.get("payload", {}).get("booking") or {}
    if hasattr(updated_booking, "model_dump"):
        updated_booking = updated_booking.model_dump()

    staff_name_resolved = _staff_display_name(context, staff_id)
    return {
        "success": True,
        "appointment": {
            "appointment_id": updated_booking.get("id") or booking_id,
            "date": updated_booking.get("start_at") or start_at,
            "service": service,
            "staff_id": staff_id,
            "staff_name": staff_name_resolved,
            "status": updated_booking.get("status") or booking.get("status"),
        },
    }


async def forward_call_to_location(connection_id: Optional[str]) -> Dict[str, Any]:
    """Forward the active call to the business location phone number."""
    logger.info("business_logic.forward_call_to_location called (connection_id=%s)", connection_id)
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
    service: str,
    connection_id: Optional[str] = None,
    staff_ids: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Fetch availability from Square search_availability."""
    logger.debug(
        "business_logic.get_available_appointment_slots called (start_date=%s end_date=%s service=%s connection_id=%s)",
        start_date,
        end_date,
        service,
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
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    logger.debug(
        "Availability context (location_id=%s token_present=%s)",
        location_id,
        bool(access_token),
    )
    if not access_token:
        logger.warning(
            "Missing auth context for %s (locationId=%s, token=%s)",
            connection_id,
            location_id,
            bool(access_token),
        )
        return {"success": False, "error": "Missing access token."}

    if provider == "setmore":
        timezone_name = _resolve_location_timezone(context)
        tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
        start_at_local, _ = _resolve_date_range(start_date, end_date, tzinfo)
        start_at_local, _ = _ensure_minimum_range(start_at_local, start_at_local + timedelta(days=1))
        selected_date = _setmore_format_date(start_at_local)

        service_item = _setmore_match_service(context, service)
        if not service_item:
            suggestions = [item.get("name") for item in context.get("services") or [] if item.get("name")]
            response = {"success": False, "error": "Service not available for booking."}
            if suggestions:
                response["suggested_services"] = suggestions[:5]
            return response
        service_key = service_item.get("id")
        if not service_key:
            return {"success": False, "error": "Service key not found."}

        resolved_staff_id = _setmore_resolve_staff_key(context, staff_ids or [])
        if staff_ids and not resolved_staff_id:
            return {
                "success": False,
                "error": "Requested staff not found. Please confirm the staff member name.",
            }
        if not resolved_staff_id:
            return {"success": False, "error": "No staff available for booking."}

        payload = {
            "staff_key": resolved_staff_id,
            "service_key": service_key,
            "selected_date": selected_date,
        }
        if timezone_name:
            payload["timezone"] = timezone_name
        slots_result = await setmore_api.fetch_slots(access_token, payload)
        if not slots_result.get("success"):
            return {"success": False, "error": slots_result.get("error")}
        slots = []
        for slot in slots_result.get("slots") or []:
            iso_value = _setmore_slot_to_iso(start_at_local, slot, tzinfo)
            if not iso_value:
                continue
            slots.append(
                {
                    "start_at": iso_value,
                    "date": iso_value.split("T")[0],
                    "time": iso_value.split("T")[-1][:5],
                }
            )
        available_staff = [
            member for member in context.get("staff") or [] if member.get("id") == resolved_staff_id
        ]
        return {
            "success": True,
            "availability_mode": "slots",
            "slots": slots,
            "ranges": [],
            "available_staff": available_staff,
        }

    if not location_id:
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
    resolved_staff_ids, unmatched_staff = _resolve_staff_ids(context, staff_ids or [])
    if staff_ids and (not resolved_staff_ids or unmatched_staff):
        logger.warning(
            "Staff resolution mismatch (requested=%s resolved=%s unmatched=%s)",
            staff_ids,
            resolved_staff_ids,
            unmatched_staff,
        )
        return {
            "success": False,
            "error": "Requested staff not found. Please confirm the staff member name.",
            "unmatched_staff": unmatched_staff,
        }

    service_variation_id, _, _ = booking_helpers.match_service_variation(context, service)
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    filter_payload = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
    }
    filter_payload["segment_filters"] = [{"service_variation_id": service_variation_id}]
    if resolved_staff_ids:
        if "segment_filters" not in filter_payload:
            filter_payload["segment_filters"] = [{}]
        filter_payload["segment_filters"][0]["team_member_id_filter"] = {"any": resolved_staff_ids}

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
    if resolved_staff_ids:
        staff_id_set = set(resolved_staff_ids)
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
    provider = _provider_from_context(context)
    access_token = context.get("accessToken") or context.get("access_token")
    if not access_token:
        return {"success": False, "error": "Access token not available."}
    if provider == "setmore":
        return {"success": False, "error": "Setmore customer prefetch not supported."}

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
    logger.info("business_logic.prepare_farewell_message called (farewell_type=%s)", farewell_type)
    _ = websocket
    return {
        "success": True,
        "farewell_type": farewell_type,
        "message": message,
    }
