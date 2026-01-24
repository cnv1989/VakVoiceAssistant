"""
Strands tool wrappers for voice assistant functions.
These tools can be used with Strands agents in the /chat endpoint.

Tools receive business context via tool_context parameter which is passed
deterministically from the agent invocation.
"""
import inspect
import logging
import uuid
from typing import Optional
from strands import tool
from strands.types.tools import ToolContext
import config
from business_logic import (
    get_customer as _get_customer,
    get_customer_appointments as _get_customer_appointments,
    get_customer_orders as _get_customer_orders,
    create_customer as _create_customer,
    schedule_appointment_with_contact as _schedule_appointment_with_contact,
    update_appointment as _update_appointment,
    get_available_appointment_slots as _get_available_appointment_slots,
)
from connection_store import set_connection_context, clear_connection_context
from store_tools import (
    get_store_hours_from_context as _get_store_hours,
    get_store_location_from_context as _get_store_location,
    get_services_from_context as _get_services,
    get_staff_from_context as _get_staff,
)

logger = logging.getLogger(__name__)


def _get_business_context_from_tool(tool_context: Optional[ToolContext]) -> dict:
    """Extract business context from tool_context.agent.state."""
    if not tool_context:
        return {}

    # Primary path: tool_context.agent.state contains business_context
    return tool_context.agent.state.get("business_context")


async def _call_with_connection_context(business_context: dict, func, **kwargs) -> dict:
    """Invoke business logic with a temporary connection context for chat tools."""
    connection_id = f"chat-{uuid.uuid4().hex}"
    set_connection_context(connection_id, business_context)
    try:
        params = dict(kwargs)
        if "connection_id" in inspect.signature(func).parameters:
            params["connection_id"] = connection_id
        return await func(**params)
    finally:
        clear_connection_context(connection_id)


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


@tool(context=True)
async def find_customer(
    tool_context: ToolContext,
    customer_id: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """Look up a customer's account information by phone, email, or ID.

    Use this before appointments or order lookups when you need a customer ID.
    Customer ID formats: Numbers only (e.g., '169', '42') -> Format as 'CUST0169', 'CUST0042'
    Phone number: Format as +1XXXXXXXXXX (add +1 if not provided, remove spaces/dashes)
    Email: Standard format (e.g., 'john.smith@example.com')
    """
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "customer_id": customer_id,
        "phone": phone,
        "email": email,
    }
    return await _call_with_connection_context(business_context, _get_customer, **params)


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
    return await _call_with_connection_context(
        business_context,
        _get_customer_appointments,
        customer_id=customer_id,
    )


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
    business_context = _get_business_context_from_tool(tool_context)
    return await _get_customer_orders(customer_id)


@tool(context=True)
async def create_customer(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
) -> dict:
    """Create a new customer in Square.

    Use when the customer is new and you need a customer_id before booking.
    The caller is a new customer and you need to create their account.
    You have confirmed first and last name, and optionally phone number.
    """
    business_context = _get_business_context_from_tool(tool_context)
    # Use caller's phone if not provided
    if not phone_number:
        phone_number = business_context.get("caller")
    return await _call_with_connection_context(
        business_context,
        _create_customer,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone_number,
    )


@tool(context=True)
async def create_appointment(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    customer_id: str,
    staff_id: str,
    date: str,
    service: str,
    phone_number: Optional[str] = None,
) -> dict:
    """Schedule a new appointment for a customer.

    Use this when a customer wants to book a new appointment or asks to schedule a service.
    Before scheduling:
    1. Ask for a preferred day/date or whether they want week availability
    2. Check availability using check_availability
    3. Confirm date/time and service type with the customer (must be an available slot)
    4. Collect first and last name and confirm spelling before booking
    5. If the customer exists, pass their customer_id; if not, create the customer first.
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = _get_business_context_from_tool(tool_context)
    # Use caller's phone if not provided
    if not phone_number:
        phone_number = business_context.get("caller")
    return await _call_with_connection_context(
        business_context,
        _schedule_appointment_with_contact,
        first_name=first_name,
        last_name=last_name,
        customer_id=customer_id,
        staff_id=staff_id,
        date=date,
        service=service,
        phone_number=phone_number,
    )


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
    return await _call_with_connection_context(
        business_context,
        _update_appointment,
        booking_id=booking_id,
        date=date,
        service=service,
        staff_id=staff_id,
        staff_name=staff_name,
    )


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
    return await _call_with_connection_context(
        business_context,
        _get_available_appointment_slots,
        start_date=start_date,
        end_date=end_date,
        service=service,
        staff_ids=staff_ids,
    )


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
