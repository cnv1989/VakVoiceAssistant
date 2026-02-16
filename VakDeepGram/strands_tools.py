"""
DEPRECATED — this module has been superseded by the providers/ package.

The provider-specific tools are now split into:
    providers/square/tools.py   — Square-only tools
    providers/setmore/tools.py  — Setmore-only tools
    providers/common/tools.py   — shared tools (store info, selection, greeting)

This file is kept for backward compatibility; new code should import from
providers instead:

    from providers import get_tools_for_provider
"""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from strands import tool
from strands.types.tools import ToolContext
import config
from square import AsyncSquare
from utils import setmore_api
from utils import booking_helpers
from store_tools import (
    get_store_hours_from_context as _get_store_hours,
    get_store_location_from_context as _get_store_location,
    get_services_from_context as _get_services,
    get_staff_from_context as _get_staff,
)
from utils.phone import normalize_phone_number, phone_digit_variants
from utils.square_helpers import (
    get_square_environment,
    parse_square_response,
    extract_square_cursor,
)
from business_logic import send_booking_link_sms, send_booking_link_whatsapp, build_setmore_booking_url

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


def _get_business_context_from_tool(tool_context: Optional[ToolContext]) -> dict:
    """Extract business context from tool_context.agent.state."""
    if not tool_context:
        return {}

    # Primary path: tool_context.agent.state contains business_context
    return tool_context.agent.state.get("business_context")


def _update_business_context(tool_context: ToolContext, updates: dict) -> dict:
    """Persist chat selections in the agent state."""
    if not tool_context or not getattr(tool_context, "agent", None):
        return {}
    state = tool_context.agent.state or {}
    business_context = state.get("business_context") or {}
    business_context.update(updates)
    state["business_context"] = business_context
    tool_context.agent.state = state
    return business_context


def _get_access_context(business_context: dict, require_location: bool = True) -> dict:
    access_token = business_context.get("accessToken") or business_context.get("access_token")
    location_id = business_context.get("locationId") or business_context.get("location_id")
    refresh_token = business_context.get("refreshToken") or business_context.get("refresh_token")
    if not access_token:
        return {"success": False, "error": "Missing Square access token."}
    if require_location and not location_id:
        return {"success": False, "error": "Missing Square location ID."}
    return {"success": True, "access_token": access_token, "location_id": location_id, "refresh_token": refresh_token}


def _get_square_client(access_token: str) -> AsyncSquare:
    from utils.square_client import get_square_client
    return get_square_client(access_token)


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


async def _collect_async_pager(pager) -> list[dict]:
    items: list[dict] = []
    async for item in pager:
        items.append(_as_dict(item))
    return items


async def _find_customer_by_phone(client: AsyncSquare, phone: str) -> Optional[dict]:
    response = await client.customers.list(limit=100)
    parsed = parse_square_response(response)
    if not parsed.get("success"):
        return None
    if parsed.get("payload", {}).get("iterable"):
        customers = await _collect_async_pager(response)
    else:
        customers = parsed.get("payload", {}).get("customers") or []
    target_digits = phone_digit_variants(phone)
    if not target_digits:
        return None
    for customer in customers:
        customer_dict = _as_dict(customer)
        customer_phone = customer_dict.get("phone_number") or customer_dict.get("phoneNumber")
        if not customer_phone:
            continue
        customer_digits = phone_digit_variants(customer_phone)
        if customer_digits and target_digits.intersection(customer_digits):
            return customer_dict
    return None


def _select_service_variation_id(context: Dict[str, Any]) -> Optional[str]:
    return booking_helpers.select_service_variation_id(context)


def _match_service_variation(
    context: Dict[str, Any],
    service_name: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    return booking_helpers.match_service_variation(context, service_name)


def _normalize_iso(value: str) -> str:
    return booking_helpers.normalize_iso(value)


def _parse_datetime(value: str) -> datetime:
    return booking_helpers.parse_datetime(value)


def _isoformat_utc(value: datetime) -> str:
    return booking_helpers.isoformat_utc(value)


def _start_of_day(dt_value: datetime) -> datetime:
    return booking_helpers.start_of_day(dt_value)


def _end_of_day(dt_value: datetime) -> datetime:
    return booking_helpers.end_of_day(dt_value)


def _ensure_minimum_range(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    return booking_helpers.ensure_minimum_range(start_at, end_at)


def _resolve_location_timezone(context: Dict[str, Any]) -> Optional[str]:
    return booking_helpers.resolve_location_timezone(context)


def _availability_start_at(availability: Any) -> Optional[str]:
    return booking_helpers.availability_start_at(availability)


def _availability_duration_minutes(availability: Any) -> Optional[int]:
    return booking_helpers.availability_duration_minutes(availability)


def _availability_team_member_ids(availability: Any) -> list[str]:
    return booking_helpers.availability_team_member_ids(availability)


def _availability_start_dt(availability: Any, tzinfo) -> Optional[datetime]:
    return booking_helpers.availability_start_dt(availability, tzinfo)


def _availability_supports_start(
    availability: Any,
    start_dt: datetime,
    duration_minutes: Optional[int],
    tzinfo,
    tolerance_minutes: int,
) -> bool:
    return booking_helpers.availability_supports_start(
        availability,
        start_dt,
        duration_minutes,
        tzinfo,
        tolerance_minutes,
    )


def _resolve_available_staff(context: Dict[str, Any], availabilities: list[Any]) -> list[Dict[str, Any]]:
    return booking_helpers.resolve_available_staff(context, availabilities)


def _resolve_staff_ids(context: Dict[str, Any], requested: list[Any]) -> tuple[list[str], list[str]]:
    return booking_helpers.resolve_staff_ids(context, requested)


def _staff_display_name(context: Dict[str, Any], staff_id: Optional[str]) -> Optional[str]:
    return booking_helpers.staff_display_name(context, staff_id)


def _availability_window_minutes(service: Optional[str], duration_minutes: Optional[int]) -> int:
    return booking_helpers.availability_window_minutes(service, duration_minutes)


def _format_availability_response(availabilities: list[Any], tzinfo) -> Dict[str, Any]:
    return booking_helpers.format_availability_response(availabilities, tzinfo)


def _booking_segments(booking: Any) -> list[Dict[str, Any]]:
    return booking_helpers.booking_segments(booking)


def _booking_version(booking: Any) -> Optional[int]:
    return booking_helpers.booking_version(booking)


def _extract_booking_segment_details(booking: Any) -> Dict[str, Any]:
    return booking_helpers.extract_booking_segment_details(booking)


def _relative_range(name: str, now: datetime) -> tuple[datetime, datetime]:
    return booking_helpers.relative_range(name, now)


def _resolve_weekday_range(value: str, now: datetime) -> Optional[tuple[datetime, datetime]]:
    return booking_helpers.resolve_weekday_range(value, now)


def _resolve_date_range(
    start_value: str,
    end_value: Optional[str],
    tzinfo,
) -> tuple[datetime, datetime]:
    return booking_helpers.resolve_date_range(start_value, end_value, tzinfo)


@tool(context=True)
async def find_customer(
    tool_context: ToolContext,
    phone: Optional[str] = None,
    caller_number: Optional[str] = None,
    first_name: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """Look up a customer's account information by phone number.

    Use this before appointments or order lookups when you need a customer ID.
    Phone number: Format as +1XXXXXXXXXX (add +1 if not provided, remove spaces/dashes).
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not any([phone, caller_number]):
        context_customer = business_context.get("customer")
        if context_customer:
            return {"success": True, "customer": _as_dict(context_customer), "new_customer": False}
        phone = business_context.get("caller")
    phone = phone or caller_number
    if not phone:
        return {"error": "phone is required"}

    context_info = _get_access_context(business_context, require_location=False)
    if not context_info.get("success"):
        return context_info
    provider = _provider_from_context(business_context)

    if provider == "setmore":
        if not first_name:
            return {"success": False, "error": "first_name is required for Setmore customer lookup."}
        normalized = normalize_phone_number(phone) if phone else None
        result = await setmore_api.fetch_customer(
            context_info["access_token"],
            first_name=first_name,
            phone=normalized,
            email=email,
            refresh_token=context_info.get("refresh_token"),
        )
        if not result.get("success"):
            return {"success": False, "error": result.get("error")}
        customers = result.get("customers") or []
        if customers:
            return {"success": True, "customer": customers[0], "new_customer": False}
        return {"success": False, "error": "Customer not found.", "new_customer": True}

    client = _get_square_client(context_info["access_token"])
    if phone:
        normalized = normalize_phone_number(phone) or phone
        customer = await _find_customer_by_phone(client, normalized)
        if customer:
            return {"success": True, "customer": customer, "new_customer": False}
        return {"success": False, "error": "Customer not found.", "new_customer": True}

    return {"success": False, "error": "Customer not found.", "new_customer": True}


@tool(context=True)
async def get_appointments(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Retrieve all appointments for a customer.

    Use this when a customer asks about their upcoming appointments or wants to know their schedule.
    Always verify you have the customer's account first using find_customer before checking appointments.
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not customer_id:
        return {"success": False, "error": "customer_id is required"}
    context_info = _get_access_context(business_context, require_location=False)
    if not context_info.get("success"):
        return context_info
    provider = _provider_from_context(business_context)
    timezone_name = _resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name else None
    now = datetime.now(tzinfo) if tzinfo else datetime.now()

    if provider == "setmore":
        start_date = (now - timedelta(days=1)).strftime("%d-%m-%Y")
        end_date = (now + timedelta(days=90)).strftime("%d-%m-%Y")
        result = await setmore_api.fetch_appointments(
            context_info["access_token"],
            start_date=start_date,
            end_date=end_date,
            refresh_token=context_info.get("refresh_token"),
            customer_details=True,
        )
        if not result.get("success"):
            return {"success": False, "error": result.get("error")}
        appointments = [appt for appt in (result.get("appointments") or []) if appt.get("customer_key") == customer_id]
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
                }
            )
        return {"success": True, "appointments": formatted}

    client = _get_square_client(context_info["access_token"])
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
        parsed = parse_square_response(response)
        if not parsed.get("success"):
            return {"success": False, "error": parsed.get("error")}
        if parsed.get("payload", {}).get("iterable"):
            page_items = await _collect_async_pager(response)
            appointments.extend(page_items)
            cursor = extract_square_cursor(response)
        else:
            payload = parsed.get("payload", {})
            appointments.extend(payload.get("bookings") or [])
            cursor = payload.get("cursor")
        if not cursor:
            break

    formatted: list[Dict[str, Any]] = []
    for booking in appointments:
        booking = _as_dict(booking)
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


@tool(context=True)
async def get_orders(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Retrieve order history for a customer.

    Use this when a customer asks about their orders, wants to check order status,
    or asks questions like 'Where is my order?' or 'What did I order?'
    Always verify you have the customer's account first using find_customer before checking orders.
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
async def create_customer(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    caller_number: Optional[str] = None,
) -> dict:
    """Create a new customer in Square.

    Use when the customer is new and you need a customer_id before booking.
    The caller is a new customer and you need to create their account.
    You have confirmed first and last name, and optionally phone number.
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not first_name or not last_name:
        return {"success": False, "error": "first_name and last_name are required"}
    if not phone_number:
        phone_number = caller_number or business_context.get("caller")
    if not phone_number:
        return {"success": False, "error": "phone_number is required for customer creation."}

    context_info = _get_access_context(business_context, require_location=False)
    if not context_info.get("success"):
        return context_info
    provider = _provider_from_context(business_context)

    if provider == "setmore":
        normalized_phone = normalize_phone_number(phone_number) or phone_number
        payload = {"first_name": first_name, "last_name": last_name}
        if normalized_phone:
            payload["cell_phone"] = normalized_phone
        created = await setmore_api.create_customer(context_info["access_token"], payload, refresh_token=context_info.get("refresh_token"))
        if not created.get("success"):
            return {"success": False, "error": created.get("error")}
        return {"success": True, "customer": created.get("customer")}

    client = _get_square_client(context_info["access_token"])

    normalized_phone = normalize_phone_number(phone_number) or phone_number
    existing = await _find_customer_by_phone(client, normalized_phone)
    if existing:
        return {
            "success": True,
            "customer": existing,
            "duplicate": True,
            "message": "Customer already exists. Confirm before using existing record.",
        }

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
    return {"success": True, "customer": _as_dict(customer)}


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

    Use this when a customer wants to book a new appointment or asks to schedule a service.
    Before scheduling:
    1. Ask for a preferred day/date or whether they want week availability
    2. Check availability using check_availability
    3. Confirm date/time and service type with the customer (must be an available slot)
    4. Collect first and last name and confirm spelling before booking
    5. If the customer exists, pass their customer_id; if not, create the customer first.
    If staff_id is omitted, the system picks an available staff member.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).

    For Setmore: Instead of booking directly, sends the customer a text message with a booking
    link and prefilled appointment details (service, staff, date/time). Tell the customer you
    are sending them a text with the booking link to complete their appointment.
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not all([first_name, last_name, date, service]):
        return {"success": False, "error": "first_name, last_name, date, and service are required"}

    if not phone_number:
        phone_number = caller_number or business_context.get("caller")

    provider = _provider_from_context(business_context)
    logger.info("create_appointment called: provider=%s service=%s date=%s phone=%s", provider, service, date, phone_number)
    context_info = _get_access_context(business_context, require_location=(provider != "setmore"))
    if not context_info.get("success"):
        logger.error("create_appointment: access context failed: %s", context_info.get("error"))
        return context_info
    if provider == "setmore":
        timezone_name = _resolve_location_timezone(business_context)
        tzinfo = ZoneInfo(timezone_name) if timezone_name else None
        start_dt = _parse_datetime(date)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
        elif tzinfo:
            start_dt = start_dt.astimezone(tzinfo)

        service_item = _setmore_match_service(business_context, service)
        if not service_item:
            suggestions = booking_helpers.suggest_services(business_context, service)
            response = {"success": False, "error": "Service not available for booking."}
            if suggestions:
                response["suggested_services"] = suggestions
            return response

        service_key = service_item.get("id")
        if not service_key:
            return {"success": False, "error": "Service key not found."}

        # Ensure customer exists in Setmore so their info is prefilled
        resolved_customer_id = customer_id
        if not resolved_customer_id and phone_number:
            payload = {
                "first_name": first_name,
                "last_name": last_name,
                "cell_phone": normalize_phone_number(phone_number) or phone_number,
            }
            created = await setmore_api.create_customer(context_info["access_token"], payload, refresh_token=context_info.get("refresh_token"))
            if not created.get("success"):
                return {"success": False, "error": created.get("error")}
            resolved_customer_id = (created.get("customer") or {}).get("key")

        resolved_staff_id = staff_id or _setmore_resolve_staff_key(business_context, [staff_id] if staff_id else [])
        staff_name = _staff_display_name(business_context, resolved_staff_id)
        service_name = service_item.get("name") or service

        # Build prefilled booking URL
        booking_page_url = business_context.get("bookingPageUrl") or business_context.get("booking_page_url")
        if not booking_page_url:
            logger.error("create_appointment: bookingPageUrl not set in business context")
            return {"success": False, "error": "Booking page URL not configured for this business."}

        to_number = normalize_phone_number(phone_number) if phone_number else None

        prefilled_url = build_setmore_booking_url(
            booking_page_url,
            service_key=service_key,
            staff_key=resolved_staff_id,
            start_dt=start_dt,
            customer_key=resolved_customer_id,
        )
        logger.info("create_appointment (setmore): prefilled_url=%s", prefilled_url)

        # Try WhatsApp first, then fall back to SMS
        from_number = business_context.get("businessNumber")
        whatsapp_number = (business_context.get("location") or {}).get("whatsapp_number")
        msg_sent = False
        msg_channel = None
        if to_number and (whatsapp_number or from_number):
            # Prefer WhatsApp if the business has a WhatsApp number
            if whatsapp_number:
                try:
                    wa_result = send_booking_link_whatsapp(
                        whatsapp_from=whatsapp_number,
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
                    msg_sent = wa_result.get("success", False)
                    if msg_sent:
                        msg_channel = "whatsapp"
                    else:
                        logger.warning("create_appointment: WhatsApp send failed: %s", wa_result.get("error"))
                except Exception as exc:
                    logger.warning("create_appointment: WhatsApp send exception: %s", exc)

            # Fall back to SMS if WhatsApp was not available or failed
            if not msg_sent and from_number:
                try:
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
                    msg_sent = sms_result.get("success", False)
                    if msg_sent:
                        msg_channel = "sms"
                    else:
                        logger.warning("create_appointment: SMS send failed: %s", sms_result.get("error"))
                except Exception as exc:
                    logger.warning("create_appointment: SMS send exception: %s", exc)

        return {
            "success": True,
            "booking_url": prefilled_url,
            "message_sent": msg_sent,
            "message_channel": msg_channel,
            "sms_sent": msg_sent and msg_channel == "sms",  # backward compat
            "appointment_details": {
                "date": start_dt.isoformat(),
                "service": service_name,
                "service_key": service_key,
                "staff_name": staff_name,
                "staff_key": resolved_staff_id,
                "customer_id": resolved_customer_id,
                "customer_phone": to_number,
            },
            "message": (
                f"Booking link sent to {to_number} via WhatsApp." if msg_channel == "whatsapp"
                else f"Booking link sent to {to_number} via text." if msg_channel == "sms"
                else "Share this booking link with the customer to complete their appointment."
            ),
        }

    client = _get_square_client(context_info["access_token"])
    location_id = context_info["location_id"]

    resolved_customer_id = customer_id
    if not resolved_customer_id and phone_number:
        normalized_phone = normalize_phone_number(phone_number) or phone_number
        existing = await _find_customer_by_phone(client, normalized_phone)
        if existing:
            resolved_customer_id = existing.get("id")
        else:
            try:
                created = await client.customers.create(
                    idempotency_key=str(uuid.uuid4()),
                    given_name=first_name,
                    family_name=last_name,
                    phone_number=normalized_phone,
                )
            except Exception as exc:
                return {"success": False, "error": str(exc)}
            parsed = parse_square_response(created)
            if not parsed.get("success"):
                return {"success": False, "error": parsed.get("error")}
            resolved_customer_id = (parsed.get("payload", {}).get("customer") or {}).get("id")

    if not resolved_customer_id:
        return {"success": False, "error": "Customer not found and could not be created."}

    service_variation_id, duration_minutes, service_version = _match_service_variation(
        business_context,
        service,
    )
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(business_context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    timezone_name = _resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name else None
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
    availability_response = await client.bookings.search_availability(query={"filter": availability_filter})
    availability_parsed = parse_square_response(availability_response)
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
        for member in business_context.get("staff") or []:
            member_id = member.get("id")
            if member_id in available_staff_id_set and member.get("status") == "ACTIVE":
                staff_id = member_id
                break
        if not staff_id and available_staff_id_set:
            staff_id = sorted(available_staff_id_set)[0]
        if not staff_id:
            return {"success": False, "error": "No staff availability around the requested time."}

    staff_name = _staff_display_name(business_context, staff_id)
    appointment_segment = {
        "service_variation_id": service_variation_id,
        "team_member_id": staff_id,
    }
    if service_version:
        appointment_segment["service_variation_version"] = service_version
    if duration_minutes:
        appointment_segment["duration_minutes"] = duration_minutes

    booking_payload = {
        "start_at": start_at,
        "location_id": location_id,
        "customer_id": resolved_customer_id,
        "appointment_segments": [appointment_segment],
    }
    created_booking = await client.bookings.create(
        booking=booking_payload,
        idempotency_key=str(uuid.uuid4()),
    )
    created_parsed = parse_square_response(created_booking)
    if not created_parsed.get("success"):
        return {"success": False, "error": created_parsed.get("error")}
    booking = created_parsed.get("payload", {}).get("booking") or {}
    booking = _as_dict(booking)

    return {
        "success": True,
        "appointment": {
            "appointment_id": booking.get("id"),
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
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

    Use this when a customer wants to change their appointment time or asks to reschedule.
    Before rescheduling:
    1. Confirm the booking_id
    2. Confirm the desired new date/time and service
    3. Verify availability for the new slot
    After updating, confirm the new appointment details.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not booking_id or not date:
        return {"success": False, "error": "booking_id and date are required"}

    context_info = _get_access_context(business_context)
    if not context_info.get("success"):
        return context_info
    provider = _provider_from_context(business_context)
    if provider == "setmore":
        return {"success": False, "error": "Setmore appointment updates are not supported by the API."}

    client = _get_square_client(context_info["access_token"])
    location_id = context_info["location_id"]

    booking_response = await client.bookings.retrieve(booking_id=booking_id)
    booking_parsed = parse_square_response(booking_response)
    if not booking_parsed.get("success"):
        return {"success": False, "error": booking_parsed.get("error")}
    booking = booking_parsed.get("payload", {}).get("booking") or {}
    booking = _as_dict(booking)
    version = _booking_version(booking)
    if version is None:
        return {"success": False, "error": "Booking version not available."}

    segment_details = _extract_booking_segment_details(booking)
    if staff_name and not staff_id:
        resolved_staff_ids, unmatched_staff = _resolve_staff_ids(business_context, [staff_name])
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
        service_variation_id, duration_minutes, service_version = _match_service_variation(
            business_context,
            service,
        )
    else:
        service_variation_id = segment_details.get("service_variation_id")
        duration_minutes = segment_details.get("duration_minutes")
        service_version = segment_details.get("service_variation_version")
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(business_context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    timezone_name = _resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name else None
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
    availability_response = await client.bookings.search_availability(query={"filter": availability_filter})
    availability_parsed = parse_square_response(availability_response)
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
        return {"success": False, "error": "Selected staff is not available around the requested time."}

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
    update_parsed = parse_square_response(update_response)
    if not update_parsed.get("success"):
        return {"success": False, "error": update_parsed.get("error")}
    updated_booking = update_parsed.get("payload", {}).get("booking") or {}
    updated_booking = _as_dict(updated_booking)

    staff_name_resolved = _staff_display_name(business_context, staff_id)
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


@tool(context=True)
async def check_availability(
    tool_context: ToolContext,
    start_date: str,
    service: str,
    end_date: Optional[str] = None,
    staff_ids: Optional[list] = None,
) -> dict:
    """Check available appointment slots within a date range.

    Use this when a customer wants to know available appointment times,
    before scheduling a new appointment, or when a customer asks 'When can I come in?'
    After checking availability, present options to the customer in a natural way.
    If the availability response includes ranges, summarize them as ranges instead of listing every slot.
    Only call this after the service has been selected so service_variation_id can be resolved.
    Start_date can be in ISO format (YYYY-MM-DDTHH:MM:SS.sssZ), a relative date enum like TODAY or NEXT_WEEK, or a weekday name.
    """
    business_context = _get_business_context_from_tool(tool_context)
    if not start_date:
        return {"success": False, "error": "start_date is required"}
    if not service:
        return {"success": False, "error": "service is required"}

    provider = _provider_from_context(business_context)
    context_info = _get_access_context(business_context, require_location=(provider != "setmore"))
    if not context_info.get("success"):
        return context_info

    timezone_name = _resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name else None

    # ---- Setmore availability via fetch_slots (concurrent per day in range) ----
    if provider == "setmore":
        start_at_local, end_at_local = _resolve_date_range(start_date, end_date, tzinfo)
        start_at_local, end_at_local = _ensure_minimum_range(start_at_local, end_at_local)

        service_item = _setmore_match_service(business_context, service)
        if not service_item:
            suggestions = booking_helpers.suggest_services(business_context, service)
            response = {"success": False, "error": "Service not available for booking."}
            if suggestions:
                response["suggested_services"] = suggestions
            return response
        service_key = service_item.get("id")
        if not service_key:
            return {"success": False, "error": "Service key not found."}

        # Resolve staff: either the requested one or all staff for "any staff"
        resolved_staff_id = _setmore_resolve_staff_key(business_context, staff_ids or []) if staff_ids else None
        if staff_ids:
            if not resolved_staff_id:
                return {
                    "success": False,
                    "error": "Requested staff not found. Please confirm the staff member name.",
                }
            staff_keys = [resolved_staff_id]
        else:
            staff_keys = [s.get("id") for s in (business_context.get("staff") or []) if s.get("id")]
            if not staff_keys:
                return {"success": False, "error": "No staff available for booking."}

        start_date_only = start_at_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_only = end_at_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_dts = []
        d = start_date_only
        while d <= end_date_only and len(day_dts) < 10:
            day_dts.append(d)
            d += timedelta(days=1)

        async def _fetch_slots_one_day_staff(day_dt: datetime, staff_key: str) -> tuple[datetime, str, dict]:
            payload = {
                "staff_key": staff_key,
                "service_key": service_key,
                "selected_date": _setmore_format_date(day_dt),
            }
            if timezone_name:
                payload["timezone"] = timezone_name
            result = await setmore_api.fetch_slots(
                context_info["access_token"], payload, refresh_token=context_info.get("refresh_token")
            )
            return (day_dt, staff_key, result)

        tasks = [_fetch_slots_one_day_staff(day_dt, staff_key) for day_dt in day_dts for staff_key in staff_keys]
        results = await asyncio.gather(*tasks)
        slots = []
        for day_dt, staff_key, slots_result in results:
            if not slots_result.get("success"):
                return {"success": False, "error": slots_result.get("error")}
            for slot in slots_result.get("slots") or []:
                iso_value = _setmore_slot_to_iso(day_dt, slot, tzinfo)
                if not iso_value:
                    continue
                slot_entry = {
                    "start_at": iso_value,
                    "date": iso_value.split("T")[0],
                    "time": iso_value.split("T")[-1][:5],
                }
                if len(staff_keys) > 1:
                    slot_entry["staff_id"] = staff_key
                slots.append(slot_entry)
        slots.sort(key=lambda s: s["start_at"])
        staff_id_set = set(staff_keys)
        available_staff = [m for m in business_context.get("staff") or [] if m.get("id") in staff_id_set]
        return {
            "success": True,
            "availability_mode": "slots",
            "slots": slots,
            "ranges": [],
            "available_staff": available_staff,
        }

    # ---- Square availability via search_availability ----
    client = _get_square_client(context_info["access_token"])
    location_id = context_info["location_id"]

    start_at_local, end_at_local = _resolve_date_range(start_date, end_date, tzinfo)
    start_at_local, end_at_local = _ensure_minimum_range(start_at_local, end_at_local)
    start_at = _isoformat_utc(start_at_local)
    end_at = _isoformat_utc(end_at_local)

    resolved_staff_ids, unmatched_staff = _resolve_staff_ids(business_context, staff_ids or [])
    if staff_ids and (not resolved_staff_ids or unmatched_staff):
        return {
            "success": False,
            "error": "Requested staff not found. Please confirm the staff member name.",
            "unmatched_staff": unmatched_staff,
        }

    service_variation_id, _, _ = _match_service_variation(business_context, service)
    if not service_variation_id:
        suggestions = booking_helpers.suggest_services(business_context, service)
        response = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            response["suggested_services"] = suggestions
        return response

    filter_payload = {
        "start_at_range": {"start_at": start_at, "end_at": end_at},
        "location_id": location_id,
        "segment_filters": [{"service_variation_id": service_variation_id}],
    }
    if resolved_staff_ids:
        filter_payload["segment_filters"][0]["team_member_id_filter"] = {"any": resolved_staff_ids}

    response = await client.bookings.search_availability(query={"filter": filter_payload})
    parsed = parse_square_response(response)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}

    availabilities = parsed.get("payload", {}).get("availabilities") or []
    availability = _format_availability_response(availabilities, tzinfo)
    available_staff = _resolve_available_staff(business_context, availabilities)
    if resolved_staff_ids:
        staff_id_set = set(resolved_staff_ids)
        available_staff = [member for member in available_staff if member.get("id") in staff_id_set]
    return {
        "success": True,
        "availability_mode": availability.get("mode"),
        "slots": availability.get("slots"),
        "ranges": availability.get("ranges"),
        "available_staff": available_staff,
    }


@tool(context=True)
async def select_service(
    tool_context: ToolContext,
    service: str,
) -> dict:
    """Save the customer's selected service in the connection context for reuse in availability and booking."""
    business_context = _get_business_context_from_tool(tool_context)
    updated = _update_business_context(tool_context, {"selected_service": service})
    return {"success": True, "selected_service": updated.get("selected_service")}


@tool(context=True)
async def selected_staff(
    tool_context: ToolContext,
    staff: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> dict:
    """Save the customer's selected staff in the connection context for reuse in availability and booking."""
    business_context = _get_business_context_from_tool(tool_context)
    updates = {}
    if staff:
        updates["selected_staff"] = staff
    if staff_id:
        updates["selected_staff_id"] = staff_id
    if staff_name:
        updates["selected_staff_name"] = staff_name
    updated = _update_business_context(tool_context, updates)
    return {
        "success": True,
        "selected_staff": updated.get("selected_staff"),
        "selected_staff_id": updated.get("selected_staff_id"),
        "selected_staff_name": updated.get("selected_staff_name"),
    }


@tool(context=True)
async def selected_appointment_date_and_time(
    tool_context: ToolContext,
    appointment_datetime: str,
) -> dict:
    """Save the selected appointment date and time in the connection context for reuse in booking.

    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = _get_business_context_from_tool(tool_context)
    updated = _update_business_context(
        tool_context,
        {"selected_appointment_date_and_time": appointment_datetime},
    )
    return {
        "success": True,
        "selected_appointment_date_and_time": updated.get("selected_appointment_date_and_time"),
    }


@tool(context=True)
async def get_store_hours(
    tool_context: ToolContext,
) -> dict:
    """Get store operating hours.

    Use this when customers ask:
    - 'What time do you open/close?'
    - 'Are you open on Sundays?'
    - 'What are your hours?'
    """
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
    }
    return _get_store_hours(params)


@tool(context=True)
async def get_store_location(
    tool_context: ToolContext,
) -> dict:
    """Get store location details.

    Use this when customers ask:
    - 'Where are you located?'
    - 'What's your address?'
    - 'What's your phone number?'
    """
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
    }
    return _get_store_location(params)


@tool(context=True)
async def get_services(
    tool_context: ToolContext,
) -> dict:
    """Get available services and pricing.

    Use this when customers ask:
    - 'What services do you offer?'
    - 'How much is a haircut?'
    - 'Do you offer [service]?'
    """
    business_context = _get_business_context_from_tool(tool_context)
    return _get_services({"business_context": business_context})


@tool(context=True)
async def get_staff(
    tool_context: ToolContext,
) -> dict:
    """Get staff member information.

    Use this when customers ask:
    - 'Who works there?'
    - 'Do you have a stylist who does [service]?'
    - 'Tell me about your staff.'
    Use the returned staff ids when filtering availability or booking.
    """
    business_context = _get_business_context_from_tool(tool_context)
    return _get_staff({"business_context": business_context})


@tool(context=True)
async def get_greeting_message(
    tool_context: ToolContext,
) -> dict:
    """Return a greeting message using the business name when available."""
    business_context = _get_business_context_from_tool(tool_context)
    greeting = config.settings.deepgram_agent_greeting or ""
    location = business_context.get("location") or {}
    business_name = (
        location.get("business_name")
        or location.get("name")
        or business_context.get("business_name")
    )
    if business_name:
        greeting = f"Hi, welcome to {business_name}. How can I help you today?"
    if greeting:
        greeting = (
            f"{greeting} "
            "I can help with hours, location, services and pricing, staff info, and booking or rescheduling appointments."
        )
    if greeting:
        return {"success": True, "greeting": greeting}
    return {"success": False, "error": "No greeting available."}


@tool(context=True)
async def get_current_local_time(
    tool_context: ToolContext,
) -> dict:
    """Return the current localized time for the business location."""
    business_context = _get_business_context_from_tool(tool_context)
    current_local_time = business_context.get("current_local_time")
    if current_local_time:
        return {"success": True, "current_local_time": current_local_time}
    return {"success": False, "error": "current_local_time not available."}


# List of all Strands tools for easy import
ALL_STRANDS_TOOLS = [
    find_customer,
    get_appointments,
    get_orders,
    create_customer,
    create_appointment,
    update_appointment,
    check_availability,
    select_service,
    selected_staff,
    selected_appointment_date_and_time,
    get_store_hours,
    get_store_location,
    get_services,
    get_staff,
    get_greeting_message,
    get_current_local_time,
]

# Provider-specific tool lists — Setmore does not support update_appointment or get_orders
SQUARE_STRANDS_TOOLS = list(ALL_STRANDS_TOOLS)

SETMORE_STRANDS_TOOLS = [
    find_customer,
    get_appointments,
    create_customer,
    create_appointment,
    check_availability,
    select_service,
    selected_staff,
    selected_appointment_date_and_time,
    get_store_hours,
    get_store_location,
    get_services,
    get_staff,
    get_greeting_message,
    get_current_local_time,
]


def get_strands_tools_for_provider(provider: str) -> list:
    """Return the Strands tool list appropriate for the given provider."""
    if provider == "setmore":
        return SETMORE_STRANDS_TOOLS
    return SQUARE_STRANDS_TOOLS
