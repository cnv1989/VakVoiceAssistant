"""
Store Tools Configuration for Deepgram Voice Agent
Defines function schemas and implementations for store operations
"""
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Mock data for staff
MOCK_STAFF = [
    {
        "id": "staff_001",
        "name": "Sarah Johnson",
        "role": "Stylist",
        "email": "sarah.johnson@store.com",
        "phone": "+1-555-0101",
        "specialties": ["Haircuts", "Color", "Styling"]
    },
    {
        "id": "staff_002",
        "name": "Michael Chen",
        "role": "Senior Stylist",
        "email": "michael.chen@store.com",
        "phone": "+1-555-0102",
        "specialties": ["Haircuts", "Beards", "Fades"]
    },
    {
        "id": "staff_003",
        "name": "Emily Rodriguez",
        "role": "Color Specialist",
        "email": "emily.rodriguez@store.com",
        "phone": "+1-555-0103",
        "specialties": ["Color", "Highlights", "Balayage"]
    },
    {
        "id": "staff_004",
        "name": "David Kim",
        "role": "Massage Therapist",
        "email": "david.kim@store.com",
        "phone": "+1-555-0104",
        "specialties": ["Massage", "Aromatherapy"]
    }
]

# Mock data for services
MOCK_SERVICES = [
    {
        "id": "svc_001",
        "name": "Men's Haircut",
        "description": "Professional men's haircut with styling",
        "duration": 30,
        "price": 35.00,
        "category": "Haircuts"
    },
    {
        "id": "svc_002",
        "name": "Women's Haircut",
        "description": "Professional women's haircut with styling",
        "duration": 45,
        "price": 55.00,
        "category": "Haircuts"
    },
    {
        "id": "svc_003",
        "name": "Full Color",
        "description": "Complete hair coloring service",
        "duration": 120,
        "price": 120.00,
        "category": "Color"
    },
    {
        "id": "svc_004",
        "name": "Highlights",
        "description": "Partial or full highlights",
        "duration": 90,
        "price": 95.00,
        "category": "Color"
    },
    {
        "id": "svc_005",
        "name": "Beard Trim",
        "description": "Professional beard trimming and styling",
        "duration": 20,
        "price": 25.00,
        "category": "Grooming"
    },
    {
        "id": "svc_006",
        "name": "Therapeutic Massage",
        "description": "60-minute therapeutic massage",
        "duration": 60,
        "price": 80.00,
        "category": "Wellness"
    },
    {
        "id": "svc_007",
        "name": "Deep Conditioning Treatment",
        "description": "Intensive hair conditioning treatment",
        "duration": 30,
        "price": 45.00,
        "category": "Treatments"
    }
]

def get_staff() -> Dict[str, Any]:
    """
    Get all staff members (mocked data)
    
    Returns:
        Dict with 'success' bool, 'staff' list, and optional 'error' string
    """
    logger.debug("👥 Starting get_staff: Fetching staff members")
    try:
        logger.info(f"✅ Successfully fetched {len(MOCK_STAFF)} staff members")
        logger.debug(f"👥 Staff sample: {json.dumps(MOCK_STAFF[:2], indent=2, default=str)}")
        return {
            'success': True,
            'staff': MOCK_STAFF,
            'count': len(MOCK_STAFF)
        }
    except Exception as e:
        error_msg = f"Exception fetching staff: {str(e)}"
        logger.error(f"❌ {error_msg}", exc_info=True)
        return {
            'success': False,
            'error': error_msg,
            'staff': []
        }


def get_services() -> Dict[str, Any]:
    """
    Get all services (mocked data)
    
    Returns:
        Dict with 'success' bool, 'services' list, and optional 'error' string
    """
    logger.debug("🛎️ Starting get_services: Fetching services")
    try:
        logger.info(f"✅ Successfully fetched {len(MOCK_SERVICES)} services")
        logger.debug(f"🛎️ Services sample: {json.dumps(MOCK_SERVICES[:3], indent=2, default=str)}")
        return {
            'success': True,
            'services': MOCK_SERVICES,
            'count': len(MOCK_SERVICES)
        }
    except Exception as e:
        error_msg = f"Exception fetching services: {str(e)}"
        logger.error(f"❌ {error_msg}", exc_info=True)
        return {
            'success': False,
            'error': error_msg,
            'services': []
        }
