"""
Strands tool wrappers for voice assistant functions.
These tools can be used with Strands agents in the /chat endpoint.

Tools receive business context via tool_context parameter which is passed
deterministically from the agent invocation.
"""
import logging
from typing import Optional
from strands import tool
from strands.types.tools import ToolContext
from agent_functions import (
    find_customer as _find_customer,
    get_appointments as _get_appointments,
    get_orders as _get_orders,
    create_customer as _create_customer,
    create_appointment as _create_appointment,
    update_appointment_booking as _update_appointment_booking,
    check_availability as _check_availability,
    select_service as _select_service,
    selected_staff as _selected_staff,
    selected_appointment_date_and_time as _selected_appointment_date_and_time,
    get_store_hours as _get_store_hours,
    get_store_location as _get_store_location,
    get_services as _get_services,
    get_staff as _get_staff,
)

logger = logging.getLogger(__name__)


def _get_business_context_from_tool(tool_context: Optional[ToolContext]) -> dict:
    """Extract business context from tool_context."""
    if not tool_context:
        return {}
    # tool_context has a 'state' attribute that holds the context data
    if hasattr(tool_context, 'state') and tool_context.state:
        return tool_context.state.get('business_context', {})
    return {}


@tool
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
        "business_context": business_context,
        "customer_id": customer_id,
        "phone": phone,
        "email": email,
    }
    return await _find_customer(params)


@tool
async def get_appointments(
    tool_context: ToolContext,
    customer_id: str,
) -> dict:
    """Retrieve all appointments for a customer.

    Use this when a customer asks about their upcoming appointments or wants to know their schedule.
    Always verify you have the customer's account first using find_customer before checking appointments.
    """
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
        "customer_id": customer_id,
    }
    return await _get_appointments(params)


@tool
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
    params = {
        "business_context": business_context,
        "customer_id": customer_id,
    }
    return await _get_orders(params)


@tool
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
    params = {
        "business_context": business_context,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone_number,
    }
    return await _create_customer(params)


@tool
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
    params = {
        "business_context": business_context,
        "first_name": first_name,
        "last_name": last_name,
        "customer_id": customer_id,
        "staff_id": staff_id,
        "date": date,
        "service": service,
        "phone_number": phone_number,
    }
    return await _create_appointment(params)


@tool
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
    params = {
        "business_context": business_context,
        "booking_id": booking_id,
        "date": date,
        "service": service,
        "staff_id": staff_id,
        "staff_name": staff_name,
    }
    return await _update_appointment_booking(params)


@tool
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
    params = {
        "business_context": business_context,
        "start_date": start_date,
        "end_date": end_date,
        "service": service,
        "staff_ids": staff_ids,
    }
    return await _check_availability(params)


@tool
async def select_service(
    tool_context: ToolContext,
    service: str,
) -> dict:
    """Save the customer's selected service in the connection context for reuse in availability and booking."""
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
        "service": service,
    }
    return await _select_service(params)


@tool
async def selected_staff(
    tool_context: ToolContext,
    staff: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> dict:
    """Save the customer's selected staff in the connection context for reuse in availability and booking."""
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
        "staff": staff,
        "staff_id": staff_id,
        "staff_name": staff_name,
    }
    return await _selected_staff(params)


@tool
async def selected_appointment_date_and_time(
    tool_context: ToolContext,
    appointment_datetime: str,
) -> dict:
    """Save the selected appointment date and time in the connection context for reuse in booking.

    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    business_context = _get_business_context_from_tool(tool_context)
    params = {
        "business_context": business_context,
        "appointment_datetime": appointment_datetime,
    }
    return await _selected_appointment_date_and_time(params)


@tool
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
    return await _get_store_hours(params)


@tool
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
    return await _get_store_location(params)


@tool
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
    params = {
        "business_context": business_context,
    }
    return await _get_services(params)


@tool
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
    params = {
        "business_context": business_context,
    }
    return await _get_staff(params)


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
]
