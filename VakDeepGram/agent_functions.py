from datetime import datetime, timedelta
import logging
from business_logic import (
    get_customer,
    get_customer_appointments,
    get_customer_orders,
    create_customer as create_customer_record,
    schedule_appointment_with_contact,
    update_appointment,
    get_available_appointment_slots,
    prepare_farewell_message,
    forward_call_to_location,
)
from store_tools import (
    get_services_from_context,
    get_staff_from_context,
    get_store_hours_from_context,
    get_store_location_from_context,
)
from connection_store import get_connection_context, update_connection_context

logger = logging.getLogger(__name__)


async def find_customer(params):
    """Look up a customer by phone, email, or ID."""
    logger.debug("agent_functions.find_customer called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    phone = params.get("phone")
    email = params.get("email")
    customer_id = params.get("customer_id")
    first_name = params.get("first_name")
    result = await get_customer(
        phone=phone,
        email=email,
        customer_id=customer_id,
        first_name=first_name,
        connection_id=connection_id,
    )
    return result


async def get_appointments(params):
    """Get appointments for a customer."""
    logger.debug("agent_functions.get_appointments called (keys=%s)", list(params.keys()))
    customer_id = params.get("customer_id")
    connection_id = params.get("connection_id")
    if not customer_id:
        return {"error": "customer_id is required"}
    if not connection_id:
        return {"error": "connection_id is required"}
    result = await get_customer_appointments(customer_id, connection_id=connection_id)
    return result


async def get_orders(params):
    """Get orders for a customer."""
    logger.debug("agent_functions.get_orders called (keys=%s)", list(params.keys()))
    customer_id = params.get("customer_id")
    if not customer_id:
        return {"error": "customer_id is required"}
    result = await get_customer_orders(customer_id)
    return result


async def create_customer(params):
    """Create a new customer record."""
    logger.debug("agent_functions.create_customer called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    first_name = params.get("first_name")
    last_name = params.get("last_name")
    phone_number = params.get("phone_number")
    if not all([first_name, last_name]):
        return {"error": "first_name and last_name are required"}
    result = await create_customer_record(
        connection_id,
        first_name,
        last_name,
        phone_number=phone_number,
    )
    return result


async def create_appointment(params):
    """Schedule a new appointment."""
    logger.debug("agent_functions.create_appointment called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    first_name = params.get("first_name")
    last_name = params.get("last_name")
    date = params.get("date")
    service = params.get("service")
    phone_number = params.get("phone_number")
    customer_id = params.get("customer_id")
    staff_id = params.get("staff_id")
    if not all([first_name, last_name, date, service, customer_id, staff_id]):
        return {"error": "first_name, last_name, date, service, customer_id, and staff_id are required"}
    result = await schedule_appointment_with_contact(
        connection_id,
        first_name,
        last_name,
        date,
        service,
        phone_number=phone_number,
        customer_id=customer_id,
        staff_id=staff_id,
    )
    return result


async def update_appointment_booking(params):
    """Reschedule an existing appointment."""
    logger.debug("agent_functions.update_appointment_booking called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    booking_id = params.get("booking_id")
    date = params.get("date")
    service = params.get("service")
    staff_id = params.get("staff_id")
    staff_name = params.get("staff_name") or params.get("staff")
    if not all([connection_id, booking_id, date]):
        return {"error": "connection_id, booking_id, and date are required"}
    result = await update_appointment(
        connection_id,
        booking_id,
        date,
        service=service,
        staff_id=staff_id,
        staff_name=staff_name,
    )
    return result


async def check_availability(params):
    """Check available appointment slots."""
    logger.debug("agent_functions.check_availability called (keys=%s)", list(params.keys()))
    start_date = params.get("start_date")
    if not start_date:
        return {"error": "start_date is required"}
    connection_id = params.get("connection_id")
    if not connection_id:
        return {"error": "connection_id is required"}
    service = params.get("service")
    if not service:
        context = get_connection_context(connection_id)
        service = context.get("selected_service")
    if not service:
        return {"error": "service is required"}
    end_date = params.get("end_date")
    staff_ids = params.get("staff_ids")
    if not staff_ids:
        context = get_connection_context(connection_id)
        selected_staff = context.get("selected_staff")
        selected_staff_id = context.get("selected_staff_id")
        selected_staff_name = context.get("selected_staff_name")
        staff_ids = [value for value in (selected_staff_id, selected_staff_name, selected_staff) if value]
    result = await get_available_appointment_slots(
        start_date,
        end_date,
        service,
        connection_id=connection_id,
        staff_ids=staff_ids,
    )
    return result


async def select_service(params):
    """Store the selected service in the connection context."""
    logger.debug("agent_functions.select_service called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    service = params.get("service")
    if not connection_id or not service:
        return {"error": "connection_id and service are required"}
    context = update_connection_context(connection_id, {"selected_service": service})
    return {"success": True, "selected_service": context.get("selected_service")}


async def selected_staff(params):
    """Store the selected staff in the connection context."""
    logger.debug("agent_functions.selected_staff called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    staff = params.get("staff")
    staff_id = params.get("staff_id")
    staff_name = params.get("staff_name")
    if not connection_id or not (staff or staff_id or staff_name):
        return {"error": "connection_id and staff are required"}
    updates = {}
    if staff:
        updates["selected_staff"] = staff
    if staff_id:
        updates["selected_staff_id"] = staff_id
    if staff_name:
        updates["selected_staff_name"] = staff_name
    context = update_connection_context(connection_id, updates)
    return {
        "success": True,
        "selected_staff": context.get("selected_staff"),
        "selected_staff_id": context.get("selected_staff_id"),
        "selected_staff_name": context.get("selected_staff_name"),
    }


async def selected_appointment_date_and_time(params):
    """Store the selected appointment date/time in the connection context."""
    logger.debug(
        "agent_functions.selected_appointment_date_and_time called (keys=%s)",
        list(params.keys()),
    )
    connection_id = params.get("connection_id")
    appointment_datetime = params.get("appointment_datetime")
    if not connection_id or not appointment_datetime:
        return {"error": "connection_id and appointment_datetime are required"}
    context = update_connection_context(
        connection_id,
        {"selected_appointment_date_and_time": appointment_datetime},
    )
    return {
        "success": True,
        "selected_appointment_date_and_time": context.get("selected_appointment_date_and_time"),
    }


async def select_appointment_date_and_time(params):
    """Alias for selected_appointment_date_and_time."""
    return await selected_appointment_date_and_time(params)


async def end_call(websocket, params):
    """
    End the conversation and close the connection.
    """
    logger.debug("agent_functions.end_call called (keys=%s)", list(params.keys()))
    farewell_type = params.get("farewell_type", "general")
    message = params.get("message", "Alright, have a nice day.")
    result = await prepare_farewell_message(websocket, farewell_type, message=message)
    return result


async def transfer_to_staff(params):
    """Forward the caller to the business location phone number."""
    logger.debug("agent_functions.transfer_to_staff called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    result = await forward_call_to_location(connection_id)
    return result


async def get_store_hours(params):
    """Return store hours."""
    logger.debug("agent_functions.get_store_hours called (keys=%s)", list(params.keys()))
    return get_store_hours_from_context(params)


async def get_store_location(params):
    """Return store location information."""
    logger.debug("agent_functions.get_store_location called (keys=%s)", list(params.keys()))
    return get_store_location_from_context(params)


async def get_services(params):
    """Return store services."""
    logger.debug("agent_functions.get_services called (keys=%s)", list(params.keys()))
    return get_services_from_context(params)


async def get_staff(params):
    """Return store staff information."""
    logger.debug("agent_functions.get_staff called (keys=%s)", list(params.keys()))
    return get_staff_from_context(params)


# Function definitions that will be sent to the Voice Agent API
FUNCTION_DEFINITIONS = [
    {
        "name": "find_customer",
        "description": """Look up a customer's account information.
        Use this before appointments or order lookups when you need a customer ID.
        Use context clues to determine what type of identifier the user is providing:
        Customer ID formats:
        - Numbers only (e.g., '169', '42') -> Format as 'CUST0169', 'CUST0042'
        - With prefix (e.g., 'CUST169', 'customer 42') -> Format as 'CUST0169', 'CUST0042'
        Phone number recognition:
        - Standard format: '555-123-4567' -> Format as '+15551234567'
        - With area code: '(555) 123-4567' -> Format as '+15551234567'
        - Spoken naturally: 'five five five, one two three, four five six seven' -> Format as '+15551234567'
        - International: '+1 555-123-4567' -> Use as is
        - Always add +1 country code if not provided
        Email address recognition:
        - Spoken naturally: 'my email is john dot smith at example dot com' -> Format as 'john.smith@example.com'
        - With domain: 'john.smith@example.com' -> Use as is
        - Spelled out: 'j o h n at example dot com' -> Format as 'john@example.com'""",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer's ID. Format as CUSTXXXX where XXXX is the number padded to 4 digits with leading zeros. Example: if user says '42', pass 'CUST0042'",
                },
                "phone": {
                    "type": "string",
                    "description": """Phone number with country code. Format as +1XXXXXXXXXX:
                    - Add +1 if not provided
                    - Remove any spaces, dashes, or parentheses
                    - Convert spoken numbers to digits
                    Example: 'five five five one two three four five six seven' -> '+15551234567'""",
                },
                "email": {
                    "type": "string",
                    "description": """Email address in standard format:
                    - Convert 'dot' to '.'
                    - Convert 'at' to '@'
                    - Remove spaces between spelled out letters
                    Example: 'j dot smith at example dot com' -> 'j.smith@example.com'""",
                },
                "first_name": {
                    "type": "string",
                    "description": "Customer first name (required for Setmore customer lookup).",
                },
            },
        },
    },
    {
        "name": "get_appointments",
        "description": """Retrieve all appointments for a customer. Use this when:
        - A customer asks about their upcoming appointments
        - A customer wants to know their appointment schedule
        - A customer asks 'When is my next appointment?'
        Always verify you have the customer's account first using find_customer before checking appointments.""",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "string",
                    "description": "Connection id for the current session.",
                },
                "customer_id": {
                    "type": "string",
                    "description": "Customer's ID in CUSTXXXX format. Must be obtained from find_customer first.",
                }
            },
            "required": ["connection_id", "customer_id"],
        },
    },
    {
        "name": "get_orders",
        "description": """Retrieve order history for a customer. Use this when:
        - A customer asks about their orders
        - A customer wants to check order status
        - A customer asks questions like 'Where is my order?' or 'What did I order?'
        Always verify you have the customer's account first using find_customer before checking orders.""",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer's ID in CUSTXXXX format. Must be obtained from find_customer first.",
                }
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "create_customer",
        "description": """Create a new customer in Square.
        Use when the customer is new and you need a customer_id before booking.
        - The caller is a new customer and you need to create their account
        - You have confirmed first and last name, and optionally phone number
        If phone_number is omitted, use the caller number from context.""",
        "parameters": {
            "type": "object",
            "properties": {
                "first_name": {
                    "type": "string",
                    "description": "Customer's first name.",
                },
                "last_name": {
                    "type": "string",
                    "description": "Customer's last name.",
                },
                "phone_number": {
                    "type": "string",
                    "description": "Customer phone number. If omitted, use caller number from context.",
                },
            },
            "required": ["first_name", "last_name"],
        },
    },
    {
        "name": "create_appointment",
        "description": """Schedule a new appointment for a customer. Use this when:
        - A customer wants to book a new appointment
        - A customer asks to schedule a service
        Before scheduling:
        1. Ask for a preferred day/date or whether they want week availability
        2. Check availability using check_availability
        3. Confirm date/time and service type with the customer (must be an available slot)
        4. Collect first and last name and confirm spelling before booking
        5. If the customer exists, pass their customer_id; if not, create the customer first.
        Use the caller's phone number from context unless the customer provides a different number.""",
        "parameters": {
            "type": "object",
            "properties": {
                "first_name": {
                    "type": "string",
                    "description": "Customer's first name.",
                },
                "last_name": {
                    "type": "string",
                    "description": "Customer's last name.",
                },
                "phone_number": {
                    "type": "string",
                    "description": "Customer phone number. If omitted, use caller number from context.",
                },
                "customer_id": {
                    "type": "string",
                    "description": "Square customer ID. Required for booking.",
                },
                "staff_id": {
                    "type": "string",
                    "description": "Square team member ID for the appointment. Required for booking.",
                },
                "date": {
                    "type": "string",
                    "description": "Appointment date and time in ISO format (YYYY-MM-DDTHH:MM:SS). Must be a time slot confirmed as available.",
                },
                "service": {
                    "type": "string",
                    "description": "Type of service requested. Always validate against get_services results and clarify if needed.",
                },
            },
            "required": ["first_name", "last_name", "customer_id", "staff_id", "date", "service"],
        },
    },
    {
        "name": "update_appointment",
        "description": """Reschedule an existing appointment. Use this when:
        - A customer wants to change their appointment time
        - A customer asks to reschedule
        Before rescheduling:
        1. Confirm the booking_id
        2. Confirm the desired new date/time and service
        3. Verify availability for the new slot
        After updating, confirm the new appointment details.""",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "string",
                    "description": "Connection id for the current session.",
                },
                "booking_id": {
                    "type": "string",
                    "description": "Square booking ID to update.",
                },
                "date": {
                    "type": "string",
                    "description": "New appointment date and time in ISO format (YYYY-MM-DDTHH:MM:SS).",
                },
                "service": {
                    "type": "string",
                    "description": "Updated service name, if changing the service.",
                },
                "staff_id": {
                    "type": "string",
                    "description": "Updated staff ID, if changing staff.",
                },
                "staff_name": {
                    "type": "string",
                    "description": "Updated staff name, if changing staff.",
                },
            },
            "required": ["connection_id", "booking_id", "date"],
        },
    },
    {
        "name": "check_availability",
        "description": """Check available appointment slots within a date range. Use this when:
        - A customer wants to know available appointment times
        - Before scheduling a new appointment
        - A customer asks 'When can I come in?' or 'What times are available?'
        After checking availability, present options to the customer in a natural way, like:
        'I have openings on [date] at [time] or [date] at [time]. Which works better for you? (Spell times in words, e.g., "two am", "one thirty pm".)'
        If the availability response includes ranges, summarize them as ranges instead of listing every slot.
        If available_staff is provided and the customer is open to any staff, confirm which available staff works for them.
        Only call this after the service has been selected so service_variation_id can be resolved.""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format (YYYY-MM-DDTHH:MM:SS.sssZ), a relative date enum like TODAY or NEXT_WEEK, or a weekday name like Monday/next Monday. Confirm inferred weekday dates with the customer.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in ISO format (YYYY-MM-DDTHH:MM:SS.sssZ) or relative date enum. Optional - defaults to a range based on start_date.",
                },
                "staff_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of preferred staff IDs or staff display names; will be resolved to IDs before filtering availability.",
                },
                "service": {
                    "type": "string",
                    "description": "Service requested by the customer. Required to resolve service_variation_id before checking availability.",
                },
            },
            "required": ["start_date", "service"],
        },
    },
    {
        "name": "select_service",
        "description": "Save the customer's selected service in the connection context for reuse in availability and booking.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "service": {"type": "string"},
            },
            "required": ["connection_id", "service"],
        },
    },
    {
        "name": "selected_staff",
        "description": "Save the customer's selected staff in the connection context for reuse in availability and booking.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "staff": {"type": "string"},
                "staff_id": {"type": "string"},
                "staff_name": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    },
    {
        "name": "selected_appointment_date_and_time",
        "description": "Save the selected appointment date and time in the connection context for reuse in booking.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "appointment_datetime": {"type": "string"},
            },
            "required": ["connection_id", "appointment_datetime"],
        },
    },
    {
        "name": "select_appointment_date_and_time",
        "description": "Save the selected appointment date and time in the connection context for reuse in booking.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "appointment_datetime": {"type": "string"},
            },
            "required": ["connection_id", "appointment_datetime"],
        },
    },
    {
        "name": "end_call",
        "description": """End the conversation and close the connection. Call this when:
        - User says goodbye, thank you, etc.
        - User indicates they're done ("that's all I need", "I'm all set", etc.)
        - User wants to end the conversation
        Examples of triggers:
        - "Thank you, bye!"
        - "That's all I needed, thanks"
        - "Have a good day"
        - "Goodbye"
        - "I'm done"
        Do not call this function if the user is just saying thanks but continuing the conversation.""",
        "parameters": {
            "type": "object",
            "properties": {
                "farewell_type": {
                    "type": "string",
                    "description": "Type of farewell to use in response",
                    "enum": ["thanks", "general", "help"],
                }
            },
            "required": ["farewell_type"],
        },
    },
    {
        "name": "transfer_to_staff",
        "description": """Transfer the caller to speak with a staff member. Use this when:
        - The customer asks to talk to someone
        - The customer requests a human or staff member
        The call will be forwarded to the store phone number.""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_store_hours",
        "description": """Get store operating hours. Use this when customers ask:
        - "What time do you open/close?"
        - "Are you open on Sundays?"
        - "What are your hours?" """,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_store_location",
        "description": """Get store location details. Use this when customers ask:
        - "Where are you located?"
        - "What's your address?"
        - "What's your phone number?" """,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_services",
        "description": """Get available services and pricing. Use this when customers ask:
        - "What services do you offer?"
        - "How much is a haircut?"
        - "Do you offer [service]?" """,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_staff",
        "description": """Get staff member information. Use this when customers ask:
        - "Who works there?"
        - "Do you have a stylist who does [service]?"
        - "Tell me about your staff."
        Use the returned staff ids when filtering availability or booking.""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# Map function names to their implementations
FUNCTION_MAP = {
    "find_customer": find_customer,
    "get_appointments": get_appointments,
    "get_orders": get_orders,
    "create_customer": create_customer,
    "create_appointment": create_appointment,
    "update_appointment": update_appointment_booking,
    "check_availability": check_availability,
    "end_call": end_call,
    "transfer_to_staff": transfer_to_staff,
    "get_store_hours": get_store_hours,
    "get_store_location": get_store_location,
    "get_services": get_services,
    "get_staff": get_staff,
    "select_service": select_service,
    "selected_staff": selected_staff,
    "selected_appointment_date_and_time": selected_appointment_date_and_time,
    "select_appointment_date_and_time": select_appointment_date_and_time,
}
