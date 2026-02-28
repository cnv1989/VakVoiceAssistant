#!/usr/bin/env python3
"""
Test Setmore booking link generation.

Tests generate_booking_link (replaces create_appointment). Builds prefilled
Setmore booking URLs from booking_page_url and payload:
- staff_key, service_key, customer_key (optional), start_time

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_appointment_creation
  python -m scripts.tests.test_setmore_appointment_creation --test generate-link
  python -m scripts.tests.test_setmore_appointment_creation --test real-data  # includes URL validation
  python -m scripts.tests.test_setmore_appointment_creation --test validate-url  # validate only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

import httpx

from vakdeepgram.connection_store import resolve_business_context
from utils import setmore_api

BUSINESS_NUMBER = "510 405 4454"


def validate_booking_url(url: str, timeout: float = 15.0) -> tuple[bool, int, str]:
    """Fetch the URL and verify it returns a valid booking page (HTTP 200).

    Returns (is_valid, status_code, message).
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
        if resp.status_code == 200:
            html = resp.text.lower()
            if "error" in html[:2000] and "an error has occurred" in html:
                return False, resp.status_code, "Page shows error content"
            if "setmore" in html or "book" in html or len(resp.text) > 1000:
                return True, resp.status_code, "OK"
        return False, resp.status_code, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, -1, str(e)


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


def test_generate_booking_link(
    booking_page_url: str,
    staff_key: str,
    service_key: str,
    customer_key: str,
    start_time: datetime,
) -> dict:
    """Test generating a booking link with all fields."""
    print(f"--- generate_booking_link ---")
    print(f"booking_page_url: {booking_page_url}")
    print(f"staff_key: {staff_key}")
    print(f"service_key: {service_key}")
    print(f"customer_key: {customer_key}")
    print(f"start_time: {start_time.isoformat()}")

    start_time_str = start_time.strftime("%Y-%m-%dT%H:%M")
    payload = {
        "staff_key": staff_key,
        "service_key": service_key,
        "customer_key": customer_key,
        "start_time": start_time_str,
    }

    print(f"\nPayload: {_pretty(payload)}")

    result = setmore_api.generate_booking_link(booking_page_url, payload)

    print(f"\nSuccess: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return result

    booking_url = result.get("booking_url")
    if booking_url:
        print(f"Booking URL: {booking_url[:80]}...")
        assert "setmore.com" in booking_url
        assert "/book" in booking_url
        assert "products=" in booking_url or "step=" in booking_url
    else:
        print("Warning: Success but no booking_url returned")

    print()
    return result


def test_generate_booking_link_missing_url() -> None:
    """Test that empty/missing booking_page_url returns error."""
    print("--- generate_booking_link (missing booking_page_url) ---")

    payload = {
        "staff_key": "test-staff",
        "service_key": "test-service",
        "customer_key": "test-customer",
        "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
    }

    result = setmore_api.generate_booking_link("", payload)
    print(f"Empty URL - Success: {result.get('success')} (expected: False)")
    print(f"Error: {result.get('error')}")

    result = setmore_api.generate_booking_link("  ", payload)
    print(f"Whitespace URL - Success: {result.get('success')} (expected: False)")

    print()


async def test_generate_booking_link_with_real_data(context: dict) -> None:
    """Test generating a booking link with real data from context."""
    print("--- generate_booking_link (with real data) ---")

    booking_page_url = context.get("bookingPageUrl") or context.get("booking_page_url")
    if not booking_page_url:
        print("ERROR: No bookingPageUrl in context. Cannot test.")
        return

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
    print(f"Using service: {service_name} (key: {service_key})")

    # Create a test customer
    print("\nCreating test customer...")
    customer_result = await setmore_api.create_customer(
        context["accessToken"],
        {
            "first_name": "Test",
            "last_name": f"Link{datetime.now().strftime('%Y%m%d%H%M%S')}",
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

    start_time = datetime.now(timezone.utc) + timedelta(hours=1)
    start_time = start_time.replace(minute=(start_time.minute // 15) * 15, second=0, microsecond=0)

    print(f"\nGenerating booking link for: {start_time.isoformat()}")
    result = test_generate_booking_link(
        booking_page_url, staff_key, service_key, customer_key, start_time
    )

    if result.get("success"):
        booking_url = result.get("booking_url")
        print(f"\n✅ Booking link generated successfully!")
        print(f"   Customer: {customer_name}")
        print(f"   Service: {service_name}")
        print(f"   Staff: {staff_name}")
        print(f"   Time: {start_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"   URL: {booking_url[:70]}...")
        # Validate URL is a working booking page
        is_valid, status, msg = validate_booking_url(booking_url)
        if is_valid:
            print(f"   ✓ URL validation: HTTP {status} - valid booking page")
        else:
            print(f"   ✗ URL validation: {msg}")
    else:
        print(f"\n❌ Booking link generation failed: {result.get('error')}")


async def test_validate_generated_url() -> None:
    """Generate a booking URL with real data and validate it returns HTTP 200."""
    print("--- validate generated booking URL (HTTP fetch) ---")
    context = await _resolve_context()
    booking_page_url = context.get("bookingPageUrl") or context.get("booking_page_url")
    if not booking_page_url:
        print("ERROR: No bookingPageUrl in context.")
        return
    staff_key = (context.get("staff") or [{}])[0].get("id")
    service_key = (context.get("services") or [{}])[0].get("id")
    if not staff_key or not service_key:
        print("ERROR: No staff or services in context.")
        return
    start_time = datetime.now(timezone.utc) + timedelta(days=7)
    start_time = start_time.replace(hour=14, minute=0, second=0, microsecond=0)
    payload = {
        "staff_key": staff_key,
        "service_key": service_key,
        "start_time": start_time.strftime("%Y-%m-%dT%H:%M"),
    }
    result = setmore_api.generate_booking_link(booking_page_url, payload)
    if not result.get("success"):
        print(f"FAIL: Could not generate URL: {result.get('error')}")
        return
    url = result["booking_url"]
    print(f"URL: {url[:90]}...")
    is_valid, status, msg = validate_booking_url(url)
    if is_valid:
        print(f"✓ Valid: HTTP {status} - booking page loads correctly")
    else:
        print(f"✗ Invalid: {msg}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test Setmore booking link generation")
    parser.add_argument(
        "--test",
        choices=["generate-link", "missing-url", "real-data", "validate-url", "all"],
        default="all",
        help="Which test to run",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Setmore Booking Link Generation Test")
    print("=" * 70)
    print()

    if args.test in ["missing-url", "all"]:
        test_generate_booking_link_missing_url()

    if args.test in ["generate-link", "real-data", "all"]:
        context = await _resolve_context()
        booking_page_url = context.get("bookingPageUrl") or context.get("booking_page_url")
        if booking_page_url and args.test == "generate-link":
            staff_key = (context.get("staff") or [{}])[0].get("id", "test-staff")
            service_key = (context.get("services") or [{}])[0].get("id", "test-service")
            start_time = datetime.now(timezone.utc) + timedelta(hours=1)
            test_generate_booking_link(
                booking_page_url, staff_key, service_key, "test-customer", start_time
            )
        elif args.test in ["real-data", "all"]:
            await test_generate_booking_link_with_real_data(context)

    if args.test in ["validate-url", "all"]:
        await test_validate_generated_url()

    print("=" * 70)
    print("Tests completed")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
