"""
Setmore-specific Strands tools.

These tools handle customer lookup, appointment booking (via prefilled URL),
and availability checking through the Setmore API.
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from typing import Optional

from strands import tool
from strands.types.tools import ToolContext

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]

import config
from utils import setmore_api, booking_helpers
from utils.phone import normalize_phone_number
from business_logic import send_booking_link_sms, send_booking_link_whatsapp

from providers.common.helpers import (
    get_business_context,
    update_business_context,
    get_access_token,
    parse_datetime,
    resolve_location_timezone,
    ensure_minimum_range,
)
from providers.common.tools import COMMON_TOOLS
from providers.setmore.helpers import (
    match_service,
    resolve_staff_key,
    staff_display_name,
    format_date,
    slot_to_iso,
    phone_fields,
    build_booking_url,
)

logger = logging.getLogger(__name__)


# ── Setmore access helper ────────────────────────────────────────────────────

def _get_setmore_token(business_context: dict) -> Optional[str]:
    """Get the Setmore access token from context."""
    return get_access_token(business_context)


def _get_refresh_token(business_context: dict) -> Optional[str]:
    """Get the Setmore refresh token from context for automatic 401 retry."""
    return business_context.get("refreshToken") or business_context.get("refresh_token")


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(context=True)
async def find_customer(
    tool_context: ToolContext,
    phone: Optional[str] = None,
    caller_number: Optional[str] = None,
    first_name: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """Look up a customer in Setmore by first name and optionally phone or email.

    Setmore requires first_name for customer lookup.  If first_name is not
    provided, ask the customer for their name before calling this tool.
    """
    business_context = get_business_context(tool_context)
    access_token = _get_setmore_token(business_context)
    if not access_token:
        return {"success": False, "error": "Missing Setmore access token."}

    if not first_name:
        return {"success": False, "error": "first_name is required for Setmore customer lookup."}

    refresh = _get_refresh_token(business_context)
    result = await setmore_api.fetch_customer(access_token, first_name=first_name, phone=phone, email=email, refresh_token=refresh)
    if not result.get("success"):
        return result
    customers = result.get("customers") or []
    if not customers:
        return {"success": True, "customer": None, "message": "No customer found."}
    update_business_context(tool_context, {"customer": customers[0]})
    return {"success": True, "customer": customers[0]}


@tool(context=True)
async def create_customer(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    caller_number: Optional[str] = None,
) -> dict:
    """Create a new customer in Setmore.

    Use this when find_customer returns no match and the customer wants to book.
    """
    business_context = get_business_context(tool_context)
    access_token = _get_setmore_token(business_context)
    if not access_token:
        return {"success": False, "error": "Missing Setmore access token."}

    phone = phone_number or caller_number or business_context.get("caller")
    pf = phone_fields(phone)
    payload: dict = {"first_name": first_name, "last_name": last_name}
    if pf.get("country_code"):
        payload["country_code"] = pf["country_code"]
    if pf.get("cell_phone"):
        payload["cell_phone"] = pf["cell_phone"]

    refresh = _get_refresh_token(business_context)
    result = await setmore_api.create_customer(access_token, payload, refresh_token=refresh)
    if not result.get("success"):
        return result
    customer = result.get("customer") or {}
    update_business_context(tool_context, {"customer": customer})
    return {"success": True, "customer": customer}


@tool(context=True)
async def get_appointments(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Get upcoming appointments for a Setmore customer.

    Returns appointments within the next 30 days that match the customer key.
    """
    business_context = get_business_context(tool_context)
    access_token = _get_setmore_token(business_context)
    if not access_token:
        return {"success": False, "error": "Missing Setmore access token."}

    from datetime import datetime

    now = datetime.now(timezone.utc)
    start_date = now.strftime("%d-%m-%Y")
    end_date = (now + timedelta(days=30)).strftime("%d-%m-%Y")

    refresh = _get_refresh_token(business_context)
    result = await setmore_api.fetch_appointments(
        access_token, start_date=start_date, end_date=end_date, customer_details=True,
        refresh_token=refresh,
    )
    if not result.get("success"):
        return result

    appointments = result.get("appointments") or []
    # Filter to this customer
    matched = [a for a in appointments if a.get("customer_key") == customer_id]
    return {"success": True, "appointments": matched}


@tool(context=True)
async def check_availability(
    tool_context: ToolContext,
    start_date: str,
    service: str,
    end_date: Optional[str] = None,
    staff_ids: Optional[list] = None,
) -> dict:
    """Check available appointment slots on a given date for a Setmore service.

    Returns a list of available time slots.  start_date can be ISO format,
    a relative keyword (TODAY, TOMORROW, NEXT_WEEK), or a weekday name.
    """
    business_context = get_business_context(tool_context)
    access_token = _get_setmore_token(business_context)
    if not access_token:
        return {"success": False, "error": "Missing Setmore access token."}
    if not start_date:
        return {"success": False, "error": "start_date is required"}
    if not service:
        return {"success": False, "error": "service is required"}

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None

    start_at_local, _ = booking_helpers.resolve_date_range(start_date, end_date, tzinfo)
    start_at_local, _ = ensure_minimum_range(start_at_local, start_at_local + timedelta(days=1))
    selected_date = format_date(start_at_local)

    service_item = match_service(business_context, service)
    if not service_item:
        suggestions = booking_helpers.suggest_services(business_context, service)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    service_key = service_item.get("id")
    if not service_key:
        return {"success": False, "error": "Service key not found."}

    resolved_staff = resolve_staff_key(business_context, staff_ids or [])
    if staff_ids and not resolved_staff:
        return {"success": False, "error": "Requested staff not found. Please confirm the staff member name."}
    if not resolved_staff:
        return {"success": False, "error": "No staff available for booking."}

    payload: dict = {
        "staff_key": resolved_staff,
        "service_key": service_key,
        "selected_date": selected_date,
    }
    if timezone_name:
        payload["timezone"] = timezone_name

    refresh = _get_refresh_token(business_context)
    slots_result = await setmore_api.fetch_slots(access_token, payload, refresh_token=refresh)
    if not slots_result.get("success"):
        return {"success": False, "error": slots_result.get("error")}

    slots = []
    for slot_str in slots_result.get("slots") or []:
        iso_val = slot_to_iso(start_at_local, slot_str, tzinfo)
        if iso_val:
            slots.append({"start_at": iso_val, "date": iso_val.split("T")[0], "time": iso_val.split("T")[-1][:5]})

    available_staff = [m for m in business_context.get("staff") or [] if m.get("id") == resolved_staff]
    return {"success": True, "availability_mode": "slots", "slots": slots, "ranges": [], "available_staff": available_staff}


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
    """Schedule a new appointment by generating a prefilled Setmore booking link.

    Instead of booking directly, this builds a booking URL with the service,
    staff, date/time, and customer pre-selected, then optionally sends it via SMS.
    Tell the customer you are providing them a booking link to complete their appointment.

    Before calling:
    1. Check availability using check_availability.
    2. Confirm date/time and service with the customer.
    3. Collect first and last name.
    4. If the customer exists, pass their customer_id; otherwise create the customer first.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = get_business_context(tool_context)
    access_token = _get_setmore_token(business_context)
    if not access_token:
        return {"success": False, "error": "Missing Setmore access token."}

    if not all([first_name, last_name, date, service]):
        return {"success": False, "error": "first_name, last_name, date, and service are required"}

    phone = phone_number or caller_number or business_context.get("caller")
    logger.info("setmore.create_appointment: service=%s date=%s phone=%s", service, date, phone)

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    start_dt = parse_datetime(date)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo or timezone.utc)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)

    # Match service
    service_item = match_service(business_context, service)
    if not service_item:
        suggestions = booking_helpers.suggest_services(business_context, service)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    service_key = service_item.get("id")
    if not service_key:
        return {"success": False, "error": "Service key not found."}

    # Ensure customer exists
    resolved_customer_id = customer_id
    if not resolved_customer_id and phone:
        pf = phone_fields(phone)
        payload: dict = {"first_name": first_name, "last_name": last_name}
        if pf.get("country_code"):
            payload["country_code"] = pf["country_code"]
        if pf.get("cell_phone"):
            payload["cell_phone"] = pf["cell_phone"]
        refresh = _get_refresh_token(business_context)
        created = await setmore_api.create_customer(access_token, payload, refresh_token=refresh)
        if not created.get("success"):
            return {"success": False, "error": created.get("error")}
        resolved_customer_id = (created.get("customer") or {}).get("key")

    resolved_staff = staff_id or resolve_staff_key(business_context, [staff_id] if staff_id else [])
    staff_name_str = staff_display_name(business_context, resolved_staff)
    service_name = service_item.get("name") or service

    # Build prefilled URL
    booking_page_url = business_context.get("bookingPageUrl") or business_context.get("booking_page_url")
    if not booking_page_url:
        logger.error("setmore.create_appointment: bookingPageUrl not set")
        return {"success": False, "error": "Booking page URL not configured for this business."}

    prefilled_url = build_booking_url(
        booking_page_url,
        service_key=service_key,
        staff_key=resolved_staff,
        start_dt=start_dt,
        customer_key=resolved_customer_id,
    )
    logger.info("setmore.create_appointment: url=%s", prefilled_url)

    # Try WhatsApp first, then fall back to SMS
    to_number = normalize_phone_number(phone) if phone else None
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
                    staff_name=staff_name_str,
                    start_dt=start_dt,
                    customer_first_name=first_name,
                    service_key=service_key,
                    staff_key=resolved_staff,
                    customer_key=resolved_customer_id,
                )
                msg_sent = wa_result.get("success", False)
                if msg_sent:
                    msg_channel = "whatsapp"
                else:
                    logger.warning("setmore.create_appointment: WhatsApp failed: %s", wa_result.get("error"))
            except Exception as exc:
                logger.warning("setmore.create_appointment: WhatsApp exception: %s", exc)

        # Fall back to SMS if WhatsApp was not available or failed
        if not msg_sent and from_number:
            try:
                sms_result = send_booking_link_sms(
                    from_number=from_number,
                    to_number=to_number,
                    booking_page_url=booking_page_url,
                    service_name=service_name,
                    staff_name=staff_name_str,
                    start_dt=start_dt,
                    customer_first_name=first_name,
                    service_key=service_key,
                    staff_key=resolved_staff,
                    customer_key=resolved_customer_id,
                )
                msg_sent = sms_result.get("success", False)
                if msg_sent:
                    msg_channel = "sms"
                else:
                    logger.warning("setmore.create_appointment: SMS failed: %s", sms_result.get("error"))
            except Exception as exc:
                logger.warning("setmore.create_appointment: SMS exception: %s", exc)

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
            "staff_name": staff_name_str,
            "staff_key": resolved_staff,
            "customer_id": resolved_customer_id,
            "customer_phone": to_number,
        },
        "message": (
            f"Booking link sent to {to_number} via WhatsApp." if msg_channel == "whatsapp"
            else f"Booking link sent to {to_number} via text." if msg_channel == "sms"
            else "Share this booking link with the customer to complete their appointment."
        ),
    }


# ── Tool list ─────────────────────────────────────────────────────────────────

TOOLS = [
    find_customer,
    create_customer,
    get_appointments,
    check_availability,
    create_appointment,
    *COMMON_TOOLS,
]
