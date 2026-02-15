"""
Shared Strands tools used by both Square and Setmore providers.

These tools are provider-agnostic — they read from / write to the business
context without calling any external API.
"""
from __future__ import annotations

import logging
from typing import Optional

from strands import tool
from strands.types.tools import ToolContext

import config
from store_tools import (
    get_store_hours_from_context as _get_store_hours,
    get_store_location_from_context as _get_store_location,
    get_services_from_context as _get_services,
    get_staff_from_context as _get_staff,
)
from providers.common.helpers import get_business_context, update_business_context

logger = logging.getLogger(__name__)


# ── Selection tools ───────────────────────────────────────────────────────────

@tool(context=True)
async def select_service(tool_context: ToolContext, service: str) -> dict:
    """Store the customer's service selection in context for later use."""
    update_business_context(tool_context, {"selected_service": service})
    return {"success": True, "selected_service": service}


@tool(context=True)
async def selected_staff(
    tool_context: ToolContext,
    staff: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> dict:
    """Store the customer's staff preference in context.

    Pass staff_name or staff for display, and staff_id for later API calls.
    If the customer is open to any staff, pass staff='any'.
    """
    name = staff or staff_name
    updates: dict = {}
    if name:
        updates["selected_staff"] = name
    if staff_id:
        updates["selected_staff_id"] = staff_id
    if name and name.lower() == "any":
        updates.pop("selected_staff_id", None)
    update_business_context(tool_context, updates)
    return {"success": True, **updates}


@tool(context=True)
async def selected_appointment_date_and_time(
    tool_context: ToolContext,
    appointment_datetime: str,
) -> dict:
    """Store the selected appointment date/time in context.

    Use ISO-8601 format (YYYY-MM-DDTHH:MM:SS).
    """
    update_business_context(
        tool_context, {"selected_appointment_date_and_time": appointment_datetime}
    )
    return {"success": True, "selected_appointment_date_and_time": appointment_datetime}


# ── Store-info tools ──────────────────────────────────────────────────────────

@tool(context=True)
async def get_store_hours(tool_context: ToolContext) -> dict:
    """Get the store's business hours.

    Returns a list of time periods with day-of-week, open, and close times.
    """
    ctx = get_business_context(tool_context)
    return _get_store_hours({"business_context": ctx})


@tool(context=True)
async def get_store_location(tool_context: ToolContext) -> dict:
    """Get the store's location, address, and contact information.

    Returns business name, address, phone, email, and other details.
    """
    ctx = get_business_context(tool_context)
    return _get_store_location({"business_context": ctx})


@tool(context=True)
async def get_services(tool_context: ToolContext) -> dict:
    """Get the list of services offered with pricing and duration.

    Use this to verify a requested service exists before booking.
    """
    ctx = get_business_context(tool_context)
    return _get_services({"business_context": ctx})


@tool(context=True)
async def get_staff(tool_context: ToolContext) -> dict:
    """Get the list of staff members and their status.

    Use this to look up staff IDs when a customer requests a specific person.
    """
    ctx = get_business_context(tool_context)
    return _get_staff({"business_context": ctx})


# ── Utility tools ─────────────────────────────────────────────────────────────

@tool(context=True)
async def get_greeting_message(tool_context: ToolContext) -> dict:
    """Get the greeting message for the customer.

    Returns a personalised greeting using the business name from context.
    """
    ctx = get_business_context(tool_context)
    greeting = config.settings.deepgram_agent_greeting or "Welcome! How can I help you today?"
    location = ctx.get("location") or {}
    biz_name = location.get("business_name") or location.get("name")
    if biz_name:
        greeting = f"Hi, welcome to {biz_name}! How can I help you today?"
    return {"success": True, "greeting": greeting}


@tool(context=True)
async def get_current_local_time(tool_context: ToolContext) -> dict:
    """Get the current date and time in the store's local timezone.

    Use this to interpret relative dates like 'today', 'tomorrow', or weekday
    names such as 'Monday'.
    """
    ctx = get_business_context(tool_context)
    current_time = ctx.get("current_local_time")
    if current_time:
        return {"success": True, "current_local_time": str(current_time)}
    return {"success": False, "error": "Current local time not available in context."}


# ── Collected list for easy import ────────────────────────────────────────────

COMMON_TOOLS = [
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
