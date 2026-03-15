"""
Setmore-specific Strands tools.

These tools handle customer lookup, appointment booking (via prefilled URL),
and availability checking through the Setmore API.
"""
from __future__ import annotations

import asyncio
import time
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from strands import tool
from strands.types.tools import ToolContext

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]

from vakdeepgram import config
from utils import booking_helpers
from utils.phone import normalize_phone_number
from vakdeepgram.business_logic import send_booking_link_sms, send_booking_link_whatsapp
from providers.clients import SetmoreApiClient
from vakdeepgram.services import resolve_auth_for_business_context

from providers.common.helpers import (
    get_business_context,
    update_business_context,
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
)
from utils.metrics import emit_tool_metrics, emit_missing_business_number

logger = logging.getLogger(__name__)


def tool_metric(tool_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tool_context = kwargs.get("tool_context") or (args[0] if args else None)
            start = time.monotonic()
            success = True
            error_type = None
            try:
                result = await func(*args, **kwargs)
                if isinstance(result, dict):
                    success = bool(result.get("success", True))
                return result
            except Exception as exc:
                success = False
                error_type = type(exc).__name__
                raise
            finally:
                emit_tool_metrics(tool_name, "setmore", (time.monotonic() - start) * 1000, success, error_type)
        return wrapper
    return decorator


def _normalized_eq(a: Optional[str], b: Optional[str]) -> bool:
    """True if both are truthy and normalize to the same phone number."""
    if not a or not b:
        return False
    return (normalize_phone_number(a) or a) == (normalize_phone_number(b) or b)


# ── Setmore access helper ────────────────────────────────────────────────────

async def _get_setmore_client(
    tool_context: ToolContext,
    business_context: dict,
    *,
    tool_name: str = "unknown",
) -> Optional[SetmoreApiClient]:
    """Resolve auth context and return a Setmore API client."""
    auth = await resolve_auth_for_business_context(business_context)
    if not auth.get("success"):
        logger.warning("Setmore auth unavailable in %s: %s", tool_name, auth.get("error"))
        emit_missing_business_number("setmore", tool_name)
        return None
    access_token = auth.get("access_token")
    if not access_token:
        return None
    update_business_context(tool_context, {"accessToken": access_token})
    return SetmoreApiClient(access_token, refresh_token=auth.get("refresh_token"))


# Message to ask the customer before using their caller/call-in number
_ASK_CUSTOMER_USE_CALLER_PHONE = (
    "Can I use the number you're calling or messaging from to look up your account or create one?"
)


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(context=True)
@tool_metric("find_customer")
async def find_customer(
    tool_context: ToolContext,
    phone: Optional[str] = None,
    caller_number: Optional[str] = None,
    first_name: Optional[str] = None,
    email: Optional[str] = None,
    customer_confirmed_use_of_caller_phone: Optional[bool] = None,
) -> dict:
    """Look up a customer in Setmore by first name and optionally phone or email.

    Setmore requires first_name for customer lookup. Before using the caller's phone number,
    confirm with the customer and pass customer_confirmed_use_of_caller_phone=True only after they agree.
    """
    business_context = get_business_context(tool_context)
    setmore_client = await _get_setmore_client(tool_context, business_context, tool_name="find_customer")
    if not setmore_client:
        return {"success": False, "error": "Missing Setmore access token."}

    if not first_name:
        return {"success": False, "error": "first_name is required for Setmore customer lookup."}

    phone = phone or caller_number or business_context.get("caller")
    caller_from_context = business_context.get("caller")
    if caller_from_context and phone and _normalized_eq(phone, caller_from_context):
        if customer_confirmed_use_of_caller_phone is not True:
            return {
                "success": False,
                "error": "Confirm with the customer before using their phone number.",
                "ask_customer": _ASK_CUSTOMER_USE_CALLER_PHONE,
            }

    result = await setmore_client.fetch_customer(first_name=first_name, phone=phone, email=email)
    if not result.get("success"):
        return result
    customers = result.get("customers") or []
    if not customers:
        return {"success": True, "customer": None, "message": "No customer found."}
    update_business_context(tool_context, {"customer": customers[0]})
    return {"success": True, "customer": customers[0]}


@tool(context=True)
@tool_metric("create_customer")
async def create_customer(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    caller_number: Optional[str] = None,
    customer_confirmed_use_of_caller_phone: Optional[bool] = None,
) -> dict:
    """Create a new customer in Setmore.

    Use this when find_customer returns no match and the customer wants to book.
    Before using the caller's phone number, confirm with the customer and pass
    customer_confirmed_use_of_caller_phone=True only after they agree.
    """
    business_context = get_business_context(tool_context)
    setmore_client = await _get_setmore_client(tool_context, business_context, tool_name="create_customer")
    if not setmore_client:
        return {"success": False, "error": "Missing Setmore access token."}

    phone = phone_number or caller_number or business_context.get("caller")
    if phone and business_context.get("caller") and _normalized_eq(phone, business_context.get("caller")):
        if customer_confirmed_use_of_caller_phone is not True:
            return {
                "success": False,
                "error": "Confirm with the customer before using their phone number.",
                "ask_customer": _ASK_CUSTOMER_USE_CALLER_PHONE,
            }
    pf = phone_fields(phone)
    payload: dict = {"first_name": first_name, "last_name": last_name}
    if pf.get("country_code"):
        payload["country_code"] = pf["country_code"]
    if pf.get("cell_phone"):
        payload["cell_phone"] = pf["cell_phone"]

    logger.info("create_customer: Calling Setmore API (first_name=%s, last_name=%s, phone=%s)", first_name, last_name, phone)
    result = await setmore_client.create_customer(payload)
    if not result.get("success"):
        logger.error("create_customer: Setmore API returned failure: %s", result)
        return result
    customer = result.get("customer")
    if not customer or not isinstance(customer, dict) or not customer.get("key"):
        logger.error(
            "create_customer: Setmore returned success but customer is missing/invalid: result=%s",
            result,
        )
        return {
            "success": False,
            "error": "Customer creation succeeded but customer data is missing or invalid. Please try again.",
        }
    logger.info("create_customer: Successfully created customer with key=%s", customer.get("key"))
    # Note: Setmore API may not return phone number in create response even if provided
    # The phone number is stored but may need to be fetched separately if needed
    update_business_context(tool_context, {"customer": customer})
    return {"success": True, "customer": customer}


@tool(context=True)
@tool_metric("lookup_or_create_customer_using_caller")
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
    Setmore requires first_name for lookup. If found, returns the customer. If not found and first_name and
    last_name are provided, creates a new customer with the caller's phone. If not found and name is missing,
    returns a message asking for the missing name(s).
    """
    business_context = get_business_context(tool_context)
    caller = business_context.get("caller")
    if not caller:
        logger.warning("lookup_or_create_customer_using_caller: No caller number in context")
        return {"success": False, "error": "No caller number available. Ask the customer for their phone number."}
    if customer_confirmed_use_of_caller_phone is not True:
        return {
            "success": False,
            "error": "Confirm with the customer before using their phone number.",
            "ask_customer": _ASK_CUSTOMER_USE_CALLER_PHONE,
        }

    if first_name:
        logger.info("lookup_or_create_customer_using_caller: Looking up customer (first_name=%s, caller=%s)", first_name, caller)
        result = await find_customer(
            tool_context,
            phone=caller,
            first_name=first_name,
            customer_confirmed_use_of_caller_phone=True,
        )
        if not result.get("success"):
            logger.warning("lookup_or_create_customer_using_caller: find_customer failed: %s", result)
            return result
        customer = result.get("customer")
        if customer:
            logger.info("lookup_or_create_customer_using_caller: Customer found: %s", customer.get("key"))
            return {"success": True, "customer": customer, "new_customer": False}
        logger.info("lookup_or_create_customer_using_caller: Customer not found, will create")
    else:
        return {
            "success": False,
            "error": "To look you up I need your first name. What's your first name?",
            "need_first_name": True,
        }

    if not last_name:
        return {
            "success": False,
            "error": "Customer not found. To create an account I need your last name.",
            "need_last_name": True,
        }

    logger.info("lookup_or_create_customer_using_caller: Creating customer (first_name=%s, last_name=%s, caller=%s)", first_name, last_name, caller)
    result = await create_customer(
        tool_context,
        first_name=first_name,
        last_name=last_name,
        phone_number=caller,
        customer_confirmed_use_of_caller_phone=True,
    )
    logger.info("lookup_or_create_customer_using_caller: create_customer result: success=%s, error=%s", result.get("success"), result.get("error"))
    if result.get("success") and result.get("customer"):
        update_business_context(tool_context, {"customer": result["customer"]})
    return result


@tool(context=True)
@tool_metric("get_appointments")
async def get_appointments(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Get upcoming appointments for a Setmore customer.

    Returns appointments within the next 30 days that match the customer key.
    """
    business_context = get_business_context(tool_context)
    setmore_client = await _get_setmore_client(tool_context, business_context, tool_name="get_appointments")
    if not setmore_client:
        return {"success": False, "error": "Missing Setmore access token."}

    from datetime import datetime

    now = datetime.now(timezone.utc)
    start_date = now.strftime("%d-%m-%Y")
    end_date = (now + timedelta(days=30)).strftime("%d-%m-%Y")

    result = await setmore_client.fetch_appointments(start_date=start_date, end_date=end_date, customer_details=True)
    if not result.get("success"):
        return result

    appointments = result.get("appointments") or []
    # Filter to this customer
    matched = [a for a in appointments if a.get("customer_key") == customer_id]
    return {"success": True, "appointments": matched}


@tool(context=True)
@tool_metric("check_availability")
async def check_availability(
    tool_context: ToolContext,
    start_date: str,
    service: str,
    end_date: Optional[str] = None,
    staff_ids: Optional[list] = None,
) -> dict:
    """Check available appointment slots for a Setmore service across a date range.

    Uses the given start_date and optional end_date range; fetches slots for each day
    concurrently and returns merged, sorted slots. start_date can be ISO format,
    a relative keyword (TODAY, TOMORROW, NEXT_WEEK), or a weekday name.
    """
    business_context = get_business_context(tool_context)
    setmore_client = await _get_setmore_client(tool_context, business_context, tool_name="check_availability")
    if not setmore_client:
        logger.error("check_availability: Missing Setmore access token")
        return {"success": False, "error": "Missing Setmore access token."}
    if not start_date:
        logger.error("check_availability: start_date required")
        return {"success": False, "error": "start_date is required"}
    if not service:
        logger.error("check_availability: service required")
        return {"success": False, "error": "service is required"}

    timezone_name = resolve_location_timezone(business_context)
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    try:
        start_at_local, end_at_local = booking_helpers.resolve_date_range(start_date, end_date, tzinfo)
        start_at_local, end_at_local = ensure_minimum_range(start_at_local, end_at_local)
    except Exception as e:
        logger.exception("check_availability: resolve_date_range failed start_date=%r end_date=%r: %s", start_date, end_date, e)
        return {"success": False, "error": f"Could not parse date range: {e}"}

    service_item = match_service(business_context, service)
    if not service_item:
        suggestions = booking_helpers.suggest_services(business_context, service)
        logger.warning("check_availability: service not found service=%r suggestions=%s", service, suggestions)
        resp: dict = {"success": False, "error": "Service not available for booking."}
        if suggestions:
            resp["suggested_services"] = suggestions
        return resp

    service_key = service_item.get("id")
    if not service_key:
        logger.error("check_availability: Service key not found for %s", service)
        return {"success": False, "error": "Service key not found."}

    # Resolve staff: either the requested one or all staff for "any staff"
    resolved_staff = resolve_staff_key(business_context, staff_ids or []) if staff_ids else None
    if staff_ids:
        if not resolved_staff:
            logger.warning("check_availability: Requested staff not found staff_ids=%s", staff_ids)
            return {"success": False, "error": "Requested staff not found. Please confirm the staff member name."}
        staff_keys = [resolved_staff]
    else:
        staff_keys = [m.get("id") for m in (business_context.get("staff") or []) if m.get("id")]
        if not staff_keys:
            logger.error("check_availability: No staff in context (business_context keys: %s)", list(business_context.keys()) if isinstance(business_context, dict) else type(business_context))
            return {"success": False, "error": "No staff available for booking."}

    start_date_only = start_at_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_only = end_at_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_dts = []
    d = start_date_only
    while d <= end_date_only and len(day_dts) < 10:
        day_dts.append(d)
        d += timedelta(days=1)

    async def _fetch_slots_one_day_staff(day_dt: datetime, staff_key: str) -> tuple[datetime, str, dict]:
        payload: dict = {
            "staff_key": staff_key,
            "service_key": service_key,
            "selected_date": format_date(day_dt),
        }
        if timezone_name:
            payload["timezone"] = timezone_name
        result = await setmore_client.fetch_slots(payload)
        return (day_dt, staff_key, result)

    tasks = [_fetch_slots_one_day_staff(day_dt, staff_key) for day_dt in day_dts for staff_key in staff_keys]
    results = await asyncio.gather(*tasks)
    slots: list[dict[str, Any]] = []
    for day_dt, staff_key, slots_result in results:
        if not slots_result.get("success"):
            err = slots_result.get("error")
            logger.error("check_availability: fetch_slots failed day=%s staff=%s: %s", day_dt.date(), staff_key, err)
            return {"success": False, "error": err}
        for slot_str in slots_result.get("slots") or []:
            iso_val = slot_to_iso(day_dt, slot_str, tzinfo)
            if iso_val:
                slot_entry = {"start_at": iso_val, "date": iso_val.split("T")[0], "time": iso_val.split("T")[-1][:5]}
                if len(staff_keys) > 1:
                    slot_entry["staff_id"] = staff_key
                slots.append(slot_entry)
    slots.sort(key=lambda s: s["start_at"])
    staff_id_set = set(staff_keys)
    available_staff = [m for m in business_context.get("staff") or [] if m.get("id") in staff_id_set]
    return {"success": True, "availability_mode": "slots", "slots": slots, "ranges": [], "available_staff": available_staff}


@tool(context=True)
@tool_metric("create_appointment")
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
    """Generate a prefilled booking link for the customer to complete their appointment.

    Cannot create appointments directly on Setmore. Builds a booking URL with service, staff,
    date/time, and customer prefilled. Chat: include the booking_url in your reply. Call: link
    is sent via WhatsApp; tell the customer to check WhatsApp.

    Before calling:
    1. Check availability using check_availability.
    2. Confirm date/time and service with the customer.
    3. Collect first and last name.
    4. If the customer exists, pass their customer_id; otherwise create the customer first.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = get_business_context(tool_context)
    setmore_client = await _get_setmore_client(tool_context, business_context, tool_name="create_appointment")
    if not setmore_client:
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
        logger.info("create_appointment: Creating customer (first_name=%s, last_name=%s, phone=%s)", first_name, last_name, phone)
        created = await setmore_client.create_customer(payload)
        if not created.get("success"):
            logger.error("create_appointment: Setmore API returned failure: %s", created)
            return {"success": False, "error": created.get("error")}
        customer = created.get("customer")
        if not customer or not isinstance(customer, dict) or not customer.get("key"):
            logger.error(
                "create_appointment: Setmore returned success but customer is missing/invalid: result=%s",
                created,
            )
            return {
                "success": False,
                "error": "Customer creation succeeded but customer data is missing or invalid. Please try again.",
            }
        resolved_customer_id = customer.get("key")
        logger.info("create_appointment: Successfully created customer with key=%s", resolved_customer_id)

    resolved_staff = staff_id or resolve_staff_key(business_context, [staff_id] if staff_id else [])
    if not resolved_staff:
        return {"success": False, "error": "Staff is required for appointment creation."}
    
    staff_name_str = staff_display_name(business_context, resolved_staff)
    service_name = service_item.get("name") or service

    # Get service duration to calculate end_time
    duration_minutes = service_item.get("duration_minutes") or service_item.get("duration")
    if not duration_minutes:
        # Default to 30 minutes if duration not specified
        logger.warning("setmore.create_appointment: Service duration not found, defaulting to 30 minutes")
        duration_minutes = 30
    
    # Calculate end_time
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    
    # Format times as ISO strings (Setmore expects yyyy-MM-dd'T'HH:mm format without seconds)
    # Remove timezone info and format without seconds
    start_time_local = start_dt.replace(tzinfo=None) if start_dt.tzinfo else start_dt
    end_time_local = end_dt.replace(tzinfo=None) if end_dt.tzinfo else end_dt
    start_time_str = start_time_local.strftime("%Y-%m-%dT%H:%M")
    end_time_str = end_time_local.strftime("%Y-%m-%dT%H:%M")
    
    # Generate booking link (no appointment creation)
    booking_page_url = business_context.get("bookingPageUrl") or business_context.get("booking_page_url")
    if not booking_page_url:
        return {"success": False, "error": "Booking page URL not configured for this business."}

    appointment_payload = {
        "staff_key": resolved_staff,
        "service_key": service_key,
        "customer_key": resolved_customer_id,
        "start_time": start_time_str,
        "end_time": end_time_str,
    }
    link_result = setmore_client.generate_booking_link(booking_page_url, appointment_payload)
    if not link_result.get("success"):
        return {"success": False, "error": link_result.get("error") or "Failed to generate booking link."}
    prefilled_url = link_result.get("booking_url")

    # Try WhatsApp first, then fall back to SMS
    to_number = normalize_phone_number(phone) if phone else None
    from_number = business_context.get("business_number")
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
                    connection_id=business_context.get("connection_id"),
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
                    connection_id=business_context.get("connection_id"),
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
        "appointment": None,
        "appointment_id": None,
        "booking_url": prefilled_url,
        "message_sent": msg_sent,
        "message_channel": msg_channel,
        "sms_sent": msg_sent and msg_channel == "sms",  # backward compat
        "appointment_details": {
            "date": start_dt.isoformat(),
            "end_time": end_time_str,
            "service": service_name,
            "service_key": service_key,
            "staff_name": staff_name_str,
            "staff_key": resolved_staff,
            "customer_id": resolved_customer_id,
            "customer_phone": to_number,
            "duration_minutes": duration_minutes,
        },
        "message": (
            f"Here's your booking link! Sent to {to_number} via WhatsApp." if msg_channel == "whatsapp"
            else f"Here's your booking link! Sent to {to_number} via text." if msg_channel == "sms"
            else "Here's your booking link!"
        ),
    }


# ── Tool list ─────────────────────────────────────────────────────────────────

TOOLS = [
    find_customer,
    create_customer,
    lookup_or_create_customer_using_caller,
    get_appointments,
    check_availability,
    create_appointment,
    *COMMON_TOOLS,
]
