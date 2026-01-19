from datetime import datetime, timedelta
from business_logic import (
    get_customer,
    get_customer_appointments,
    get_customer_orders,
    schedule_appointment_with_contact,
    get_available_appointment_slots,
    prepare_farewell_message,
)
from store_tools import (
    get_services_from_context,
    get_staff_from_context,
    get_store_hours_from_context,
    get_store_location_from_context,
)


async def find_customer(params):
    """Look up a customer by phone, email, or ID."""
    connection_id = params.get("connection_id")
    phone = params.get("phone")
    email = params.get("email")
    customer_id = params.get("customer_id")
    result = await get_customer(
        phone=phone,
        email=email,
        customer_id=customer_id,
        connection_id=connection_id,
    )
    return result


async def get_appointments(params):
    """Get appointments for a customer."""
    customer_id = params.get("customer_id")
    if not customer_id:
        return {"error": "customer_id is required"}
    result = await get_customer_appointments(customer_id)
    return result


async def get_orders(params):
    """Get orders for a customer."""
    customer_id = params.get("customer_id")
    if not customer_id:
        return {"error": "customer_id is required"}
    result = await get_customer_orders(customer_id)
    return result


async def create_appointment(params):
    """Schedule a new appointment."""
    connection_id = params.get("connection_id")
    first_name = params.get("first_name")
    last_name = params.get("last_name")
    date = params.get("date")
    service = params.get("service")
    phone_number = params.get("phone_number")
    if not all([first_name, last_name, date, service]):
        return {"error": "first_name, last_name, date, and service are required"}
    result = await schedule_appointment_with_contact(
        connection_id,
        first_name,
        last_name,
        date,
        service,
        phone_number=phone_number,
    )
    return result


async def check_availability(params):
    """Check available appointment slots."""
    start_date = params.get("start_date")
    if not start_date:
        return {"error": "start_date is required"}
    connection_id = params.get("connection_id")
    end_date = params.get("end_date")
    if not end_date:
        normalized_start = start_date.replace("Z", "+00:00")
        try:
            end_date = (datetime.fromisoformat(normalized_start) + timedelta(days=7)).isoformat()
        except ValueError:
            end_date = None
    result = await get_available_appointment_slots(start_date, end_date, connection_id=connection_id)
    return result


async def end_call(websocket, params):
    """
    End the conversation and close the connection.
    """
    farewell_type = params.get("farewell_type", "general")
    message = params.get("message", "Alright, have a nice day.")
    result = await prepare_farewell_message(websocket, farewell_type, message=message)
    return result


async def get_store_hours(params):
    """Return store hours."""
    return get_store_hours_from_context(params)


async def get_store_location(params):
    """Return store location information."""
    return get_store_location_from_context(params)


async def get_services(params):
    """Return store services."""
    return get_services_from_context(params)


async def get_staff(params):
    """Return store staff information."""
    return get_staff_from_context(params)


# Function definitions that will be sent to the Voice Agent API
FUNCTION_DEFINITIONS = [
    {
        "name": "find_customer",
        "description": """Look up a customer's account information. Use context clues to determine what type of identifier the user is providing:
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
            },
        },
    },
    {
        "name": "get_appointments",
        "description": """Retrieve all appointments for a customer. Use this function when:
        - A customer asks about their upcoming appointments
        - A customer wants to know their appointment schedule
        - A customer asks 'When is my next appointment?'
        Always verify you have the customer's account first using find_customer before checking appointments.""",
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
        "name": "get_orders",
        "description": """Retrieve order history for a customer. Use this function when:
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
        "name": "create_appointment",
        "description": """Schedule a new appointment for a customer. Use this function when:
        - A customer wants to book a new appointment
        - A customer asks to schedule a service
        Before scheduling:
        1. Ask for a preferred day/date or whether they want week availability
        2. Check availability using check_availability
        3. Confirm date/time and service type with the customer
        4. Collect first and last name and confirm spelling before booking
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
                "date": {
                    "type": "string",
                    "description": "Appointment date and time in ISO format (YYYY-MM-DDTHH:MM:SS). Must be a time slot confirmed as available.",
                },
                "service": {
                    "type": "string",
                    "description": "Type of service requested. Must be one of the following: Consultation, Follow-up, Review, or Planning",
                    "enum": ["Consultation", "Follow-up", "Review", "Planning"],
                },
            },
            "required": ["first_name", "last_name", "date", "service"],
        },
    },
    {
        "name": "check_availability",
        "description": """Check available appointment slots within a date range. Use this function when:
        - A customer wants to know available appointment times
        - Before scheduling a new appointment
        - A customer asks 'When can I come in?' or 'What times are available?'
        After checking availability, present options to the customer in a natural way, like:
        'I have openings on [date] at [time] or [date] at [time]. Which works better for you?'
        If the availability response includes ranges, summarize them as ranges instead of listing every slot.""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format (YYYY-MM-DDTHH:MM:SS.sssZ) or a relative date enum like TODAY, TOMORROW, YESTERDAY, THIS_WEEK, NEXT_WEEK, LAST_WEEK, THIS_WEEKEND, NEXT_WEEKEND, THIS_MONTH, NEXT_MONTH, LAST_MONTH, NEXT_7_DAYS, NEXT_14_DAYS, NEXT_30_DAYS.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in ISO format (YYYY-MM-DDTHH:MM:SS.sssZ) or relative date enum. Optional - defaults to a range based on start_date.",
                },
            },
            "required": ["start_date"],
        },
    },
    {
        "name": "end_call",
        "description": """End the conversation and close the connection. Call this function when:
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
        - "Tell me about your staff." """,
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
    "create_appointment": create_appointment,
    "check_availability": check_availability,
    "end_call": end_call,
    "get_store_hours": get_store_hours,
    "get_store_location": get_store_location,
    "get_services": get_services,
    "get_staff": get_staff,
}
