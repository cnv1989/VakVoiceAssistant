#!/usr/bin/env python3
"""
Test Setmore Appointment Creation API calls.

Tests appointment creation with required fields:
- staff_key (String, required)
- service_key (String, required)
- customer_key (String, required)
- start_time (String, required)
- end_time (String, required)

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_appointment_creation
  python -m scripts.tests.test_setmore_appointment_creation --test create-appointment
  python -m scripts.tests.test_setmore_appointment_creation --test all --cleanup  # Clean up test appointments after
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context
from utils import setmore_api
from utils.phone import normalize_phone_number

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

BUSINESS_NUMBER = "510 405 4454"


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


async def _resolve_context() -> dict:
    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        print(f"FAIL: Cannot resolve context: {context.get('error')}")
        sys.exit(1)
    provider = context.get("provider", "square")
    if provider != "setmore":
        print(f"INFO: Provider for {BUSINESS_NUMBER} is '{provider}', not 'setmore'.")
        print("This script is designed for Setmore businesses. Skipping Setmore-specific tests.")
        sys.exit(0)
    return context


async def test_create_appointment(
    context: dict,
    staff_key: str,
    service_key: str,
    customer_key: str,
    start_time: datetime,
    end_time: datetime,
) -> dict:
    """Test creating an appointment with all required fields."""
    print(f"--- create_appointment ---")
    print(f"staff_key: {staff_key}")
    print(f"service_key: {service_key}")
    print(f"customer_key: {customer_key}")
    print(f"start_time: {start_time.isoformat()}")
    print(f"end_time: {end_time.isoformat()}")
    
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Format times as ISO strings (Setmore expects yyyy-MM-dd'T'HH:mm format without seconds)
    # Convert to local timezone if needed, then format without seconds
    if start_time.tzinfo:
        # Convert to local timezone (remove timezone info for Setmore format)
        start_time_local = start_time.astimezone(timezone.utc).replace(tzinfo=None)
        end_time_local = end_time.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        start_time_local = start_time
        end_time_local = end_time
    
    start_time_str = start_time_local.strftime("%Y-%m-%dT%H:%M")
    end_time_str = end_time_local.strftime("%Y-%m-%dT%H:%M")
    
    payload = {
        "staff_key": staff_key,
        "service_key": service_key,
        "customer_key": customer_key,
        "start_time": start_time_str,
        "end_time": end_time_str,
    }
    
    print(f"\nPayload: {_pretty(payload)}")
    
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    
    print(f"\nSuccess: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return result
    
    appointment = result.get("appointment")
    if appointment:
        print(f"Appointment created:")
        print(f"  Key: {appointment.get('key')}")
        print(f"  Start Time: {appointment.get('start_time')}")
        print(f"  End Time: {appointment.get('end_time')}")
        print(f"  Staff Key: {appointment.get('staff_key')}")
        print(f"  Service Key: {appointment.get('service_key')}")
        print(f"  Customer Key: {appointment.get('customer_key')}")
        print(f"  Duration: {appointment.get('duration')} minutes")
        print(f"  Cost: {appointment.get('cost')}")
        print(f"  Currency: {appointment.get('currency')}")
    else:
        print("Warning: Appointment created but no appointment data returned")
    
    print()
    return result


async def test_create_appointment_with_service_duration(
    context: dict,
    staff_key: str,
    service_key: str,
    customer_key: str,
    start_time: datetime,
    duration_minutes: int = 30,
) -> dict:
    """Test creating an appointment by calculating end_time from duration."""
    end_time = start_time + timedelta(minutes=duration_minutes)
    return await test_create_appointment(
        context, staff_key, service_key, customer_key, start_time, end_time
    )


async def test_create_appointment_missing_fields(context: dict) -> None:
    """Test creating an appointment with missing required fields."""
    print("--- create_appointment (missing fields) ---")
    
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Test missing staff_key
    print("\n1. Testing missing staff_key...")
    payload = {
        "service_key": "test-service",
        "customer_key": "test-customer",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    print(f"   Success: {result.get('success')} (expected: False)")
    print(f"   Error: {result.get('error')}")
    
    # Test missing service_key
    print("\n2. Testing missing service_key...")
    payload = {
        "staff_key": "test-staff",
        "customer_key": "test-customer",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    print(f"   Success: {result.get('success')} (expected: False)")
    print(f"   Error: {result.get('error')}")
    
    # Test missing customer_key
    print("\n3. Testing missing customer_key...")
    payload = {
        "staff_key": "test-staff",
        "service_key": "test-service",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    print(f"   Success: {result.get('success')} (expected: False)")
    print(f"   Error: {result.get('error')}")
    
    # Test missing start_time
    print("\n4. Testing missing start_time...")
    payload = {
        "staff_key": "test-staff",
        "service_key": "test-service",
        "customer_key": "test-customer",
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    print(f"   Success: {result.get('success')} (expected: False)")
    print(f"   Error: {result.get('error')}")
    
    # Test missing end_time
    print("\n5. Testing missing end_time...")
    payload = {
        "staff_key": "test-staff",
        "service_key": "test-service",
        "customer_key": "test-customer",
        "start_time": datetime.now(timezone.utc).isoformat(),
    }
    result = await setmore_api.create_appointment(token, payload, refresh_token=refresh_token)
    print(f"   Success: {result.get('success')} (expected: False)")
    print(f"   Error: {result.get('error')}")
    
    print()


async def test_create_appointment_with_real_data(context: dict) -> None:
    """Test creating an appointment with real data from context."""
    print("--- create_appointment (with real data) ---")
    
    # Get first staff member
    staff_list = context.get("staff") or []
    if not staff_list:
        print("ERROR: No staff members found in context")
        return
    staff_key = staff_list[0].get("id")
    staff_name = f"{staff_list[0].get('first_name', '')} {staff_list[0].get('last_name', '')}".strip()
    print(f"Using staff: {staff_name} (key: {staff_key})")
    
    # Get first service
    services = context.get("services") or []
    if not services:
        print("ERROR: No services found in context")
        return
    service = services[0]
    service_key = service.get("id")
    service_name = service.get("name")
    duration_minutes = service.get("duration_minutes") or service.get("duration") or 30
    print(f"Using service: {service_name} (key: {service_key}, duration: {duration_minutes} min)")
    
    # Create a test customer first
    print("\nCreating test customer...")
    customer_result = await setmore_api.create_customer(
        context["accessToken"],
        {
            "first_name": "Test",
            "last_name": f"Appointment{datetime.now().strftime('%Y%m%d%H%M%S')}",
        },
        refresh_token=context.get("refreshToken") or context.get("refresh_token"),
    )
    
    if not customer_result.get("success"):
        print(f"ERROR: Failed to create test customer: {customer_result.get('error')}")
        return
    
    customer = customer_result.get("customer")
    if not customer or not customer.get("key"):
        print("ERROR: Customer created but missing key")
        return
    
    customer_key = customer.get("key")
    customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    print(f"Created customer: {customer_name} (key: {customer_key})")
    
    # Calculate start time (1 hour from now)
    # Use UTC for consistency with API
    start_time = datetime.now(timezone.utc) + timedelta(hours=1)
    # Round to nearest 15 minutes
    start_time = start_time.replace(minute=(start_time.minute // 15) * 15, second=0, microsecond=0)
    end_time = start_time + timedelta(minutes=duration_minutes)
    
    print(f"\nCreating appointment:")
    print(f"  Start: {start_time.isoformat()}")
    print(f"  End: {end_time.isoformat()}")
    
    # Create the appointment
    result = await test_create_appointment(
        context, staff_key, service_key, customer_key, start_time, end_time
    )
    
    if result.get("success"):
        appointment = result.get("appointment")
        if appointment:
            print(f"\n✅ Appointment created successfully!")
            print(f"   Appointment Key: {appointment.get('key')}")
            print(f"   Customer: {customer_name}")
            print(f"   Service: {service_name}")
            print(f"   Staff: {staff_name}")
            print(f"   Time: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')}")
        else:
            print("\n⚠️  Appointment creation reported success but no appointment data returned")
    else:
        print(f"\n❌ Appointment creation failed: {result.get('error')}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test Setmore appointment creation")
    parser.add_argument(
        "--test",
        choices=["create-appointment", "missing-fields", "real-data", "all"],
        default="all",
        help="Which test to run",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up test appointments after (not implemented yet)",
    )
    args = parser.parse_args()
    
    print("=" * 70)
    print("Setmore Appointment Creation Test")
    print("=" * 70)
    print()
    
    context = await _resolve_context()
    
    if args.test in ["create-appointment", "all"]:
        # This would require actual valid keys - skipping for now
        print("Skipping create-appointment test (requires valid keys)")
        print()
    
    if args.test in ["missing-fields", "all"]:
        await test_create_appointment_missing_fields(context)
    
    if args.test in ["real-data", "all"]:
        await test_create_appointment_with_real_data(context)
    
    print("=" * 70)
    print("Tests completed")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
