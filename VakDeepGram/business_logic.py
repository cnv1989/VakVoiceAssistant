"""
Mock business logic for agent function calls.
Replace with real integrations (CRM, scheduling, order systems).
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


async def get_customer(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mock customer lookup."""
    if not any([phone, email, customer_id]):
        return {"error": "phone, email, or customer_id is required"}
    return {
        "success": True,
        "customer": {
            "customer_id": customer_id or "CUST0001",
            "phone": phone or "+15551234567",
            "email": email or "customer@example.com",
            "name": "Alex Customer",
        },
    }


async def get_customer_appointments(customer_id: str) -> Dict[str, Any]:
    """Mock appointment history."""
    now = datetime.now()
    return {
        "success": True,
        "appointments": [
            {
                "appointment_id": "APT0123",
                "service": "Consultation",
                "date": (now + timedelta(days=2)).isoformat(timespec="seconds"),
                "status": "confirmed",
            }
        ],
    }


async def get_customer_orders(customer_id: str) -> Dict[str, Any]:
    """Mock order history."""
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
    return {
        "success": True,
        "appointment": {
            "appointment_id": "APT0456",
            "customer_id": customer_id,
            "date": date,
            "service": service,
            "status": "confirmed",
        },
    }


async def get_available_appointment_slots(start_date: str, end_date: str) -> Dict[str, Any]:
    """Mock availability lookup."""
    return {
        "success": True,
        "slots": [
            {"date": start_date, "time": "14:00"},
            {"date": end_date, "time": "15:00"},
        ],
    }


async def prepare_agent_filler_message(websocket, **params) -> Dict[str, Any]:
    """Mock filler message handler."""
    _ = websocket
    return {"success": True, "message_type": params.get("message_type", "general")}


async def prepare_farewell_message(websocket, farewell_type: str, message: str = "Alright, have a nice day.") -> Dict[str, Any]:
    """Mock farewell handler."""
    _ = websocket
    return {
        "success": True,
        "farewell_type": farewell_type,
        "message": message,
    }
