"""
Strands tool wrappers for voice assistant functions.
These tools can be used with Strands agents in the /chat endpoint.
"""
import logging
import threading
from typing import Optional
from strands import tool
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

# Thread-local storage for business context (works with asyncio.to_thread)
_thread_local = threading.local()

def set_chat_business_context(business_context: dict):
    """Set the business context for the current thread (chat session)."""
    _thread_local.business_context = business_context

def get_chat_business_context() -> dict:
    """Get the business context for the current thread (chat session)."""
    return getattr(_thread_local, 'business_context', {})


@tool
async def find_customer(
    customer_id: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    connection_id: Optional[str] = None,
) -> dict:
    """Look up a customer's account information by phone, email, or ID.
    
    Use this before appointments or order lookups when you need a customer ID.
    Customer ID formats: Numbers only (e.g., '169', '42') -> Format as 'CUST0169', 'CUST0042'
    Phone number: Format as +1XXXXXXXXXX (add +1 if not provided, remove spaces/dashes)
    Email: Standard format (e.g., 'john.smith@example.com')
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "customer_id": customer_id,
        "phone": phone,
        "email": email,
    }
    return await _find_customer(params)


@tool
async def get_appointments(
    customer_id: str,
    connection_id: Optional[str] = None,
) -> dict:
    """Retrieve all appointments for a customer.
    
    Use this when a customer asks about their upcoming appointments or wants to know their schedule.
    Always verify you have the customer's account first using find_customer before checking appointments.
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "customer_id": customer_id,
    }
    return await _get_appointments(params)


@tool
async def get_orders(
    customer_id: str,
) -> dict:
    """Retrieve order history for a customer.
    
    Use this when a customer asks about their orders, wants to check order status,
    or asks questions like 'Where is my order?' or 'What did I order?'
    Always verify you have the customer's account first using find_customer before checking orders.
    """
    params = {
        "customer_id": customer_id,
    }
    return await _get_orders(params)


@tool
async def create_customer(
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    connection_id: Optional[str] = None,
) -> dict:
    """Create a new customer in Square.
    
    Use when the customer is new and you need a customer_id before booking.
    The caller is a new customer and you need to create their account.
    You have confirmed first and last name, and optionally phone number.
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone_number,
    }
    return await _create_customer(params)


@tool
async def create_appointment(
    first_name: str,
    last_name: str,
    customer_id: str,
    staff_id: str,
    date: str,
    service: str,
    phone_number: Optional[str] = None,
    connection_id: Optional[str] = None,
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
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
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
    booking_id: str,
    date: str,
    connection_id: Optional[str] = None,
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
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "booking_id": booking_id,
        "date": date,
        "service": service,
        "staff_id": staff_id,
        "staff_name": staff_name,
    }
    return await _update_appointment_booking(params)


@tool
async def check_availability(
    start_date: str,
    service: str,
    connection_id: Optional[str] = None,
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
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "start_date": start_date,
        "end_date": end_date,
        "service": service,
        "staff_ids": staff_ids,
    }
    return await _check_availability(params)


@tool
async def select_service(
    service: str,
    connection_id: Optional[str] = None,
) -> dict:
    """Save the customer's selected service in the connection context for reuse in availability and booking."""
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "service": service,
    }
    return await _select_service(params)


@tool
async def selected_staff(
    connection_id: Optional[str] = None,
    staff: Optional[str] = None,
    staff_id: Optional[str] = None,
    staff_name: Optional[str] = None,
) -> dict:
    """Save the customer's selected staff in the connection context for reuse in availability and booking."""
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "staff": staff,
        "staff_id": staff_id,
        "staff_name": staff_name,
    }
    return await _selected_staff(params)


@tool
async def selected_appointment_date_and_time(
    appointment_datetime: str,
    connection_id: Optional[str] = None,
) -> dict:
    """Save the selected appointment date and time in the connection context for reuse in booking.
    
    Date should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
        "appointment_datetime": appointment_datetime,
    }
    return await _selected_appointment_date_and_time(params)


@tool
async def get_store_hours(
    connection_id: Optional[str] = None,
) -> dict:
    """Get store operating hours.
    
    Use this when customers ask:
    - 'What time do you open/close?'
    - 'Are you open on Sundays?'
    - 'What are your hours?'
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
    }
    return await _get_store_hours(params)


@tool
async def get_store_location(
    connection_id: Optional[str] = None,
) -> dict:
    """Get store location details.
    
    Use this when customers ask:
    - 'Where are you located?'
    - 'What's your address?'
    - 'What's your phone number?'
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
    }
    return await _get_store_location(params)


@tool
async def get_services(
    connection_id: Optional[str] = None,
) -> dict:
    """Get available services and pricing.
    
    Use this when customers ask:
    - 'What services do you offer?'
    - 'How much is a haircut?'
    - 'Do you offer [service]?'
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
    }
    return await _get_services(params)


@tool
async def get_staff(
    connection_id: Optional[str] = None,
) -> dict:
    """Get staff member information.
    
    Use this when customers ask:
    - 'Who works there?'
    - 'Do you have a stylist who does [service]?'
    - 'Tell me about your staff.'
    Use the returned staff ids when filtering availability or booking.
    """
    params = {
        "connection_id": connection_id,  # Can be None for chat - tools will use business context
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
