#!/usr/bin/env python3
"""
Test Setmore Customer API calls (fetch_customer, create_customer).

Tests customer lookup and creation with various scenarios:
- Lookup by first_name only
- Lookup by first_name + phone
- Lookup by first_name + email
- Create customer with required fields (first_name, last_name)
- Create customer with phone number
- Create customer without phone number
- Edge cases and error handling

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_customer_apis
  python -m scripts.tests.test_setmore_customer_apis --test fetch-customer --first-name "John"
  python -m scripts.tests.test_setmore_customer_apis --test create-customer --first-name "Test" --last-name "User" --phone "+15105551234"
  python -m scripts.tests.test_setmore_customer_apis --test all --cleanup  # Clean up test customers after
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context
from providers.setmore.helpers import phone_fields
from utils import setmore_api
from utils.phone import normalize_phone_number

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


async def test_fetch_customer_by_name(context: dict, first_name: str) -> None:
    """Test fetching customer by first_name only."""
    print(f"--- fetch_customer (first_name='{first_name}') ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    result = await setmore_api.fetch_customer(
        token, first_name=first_name, refresh_token=refresh_token
    )
    print(f"Success: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return
    
    customers = result.get("customers") or []
    print(f"Customer count: {len(customers)}")
    for cust in customers[:10]:
        key = cust.get("key")
        first = cust.get("first_name") or ""
        last = cust.get("last_name") or ""
        phone = cust.get("cell_phone") or ""
        email = cust.get("email") or ""
        print(f"  - {first} {last} (key={key}, phone={phone}, email={email})")
    if len(customers) > 10:
        print(f"  ... and {len(customers) - 10} more")
    print()


async def test_fetch_customer_by_name_and_phone(context: dict, first_name: str, phone: str) -> None:
    """Test fetching customer by first_name + phone."""
    print(f"--- fetch_customer (first_name='{first_name}', phone='{phone}') ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    normalized_phone = normalize_phone_number(phone) if phone else None
    result = await setmore_api.fetch_customer(
        token, first_name=first_name, phone=normalized_phone, refresh_token=refresh_token
    )
    print(f"Success: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return
    
    customers = result.get("customers") or []
    print(f"Customer count: {len(customers)}")
    for cust in customers[:10]:
        key = cust.get("key")
        first = cust.get("first_name") or ""
        last = cust.get("last_name") or ""
        phone_val = cust.get("cell_phone") or ""
        print(f"  - {first} {last} (key={key}, phone={phone_val})")
    print()


async def test_create_customer_minimal(context: dict) -> dict | None:
    """Test creating customer with only required fields (first_name, last_name)."""
    print("--- create_customer (minimal: first_name + last_name only) ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Use unique name to avoid conflicts
    test_id = uuid.uuid4().hex[:8]
    first_name = f"Test{test_id}"
    last_name = "User"
    
    payload = {
        "first_name": first_name,
        "last_name": last_name,
    }
    
    print(f"Payload: {_pretty(payload)}")
    result = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    print(f"Success: {result.get('success')}")
    
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return None
    
    customer = result.get("customer")
    if customer:
        key = customer.get("key")
        first = customer.get("first_name") or ""
        last = customer.get("last_name") or ""
        phone = customer.get("cell_phone") or ""
        print(f"Created customer: {first} {last} (key={key}, phone={phone})")
        print(f"Full customer data: {_pretty(customer)}")
    else:
        print("WARNING: Customer creation succeeded but customer object is missing!")
        print(f"Full result: {_pretty(result)}")
    print()
    return customer


async def test_create_customer_with_phone(context: dict, phone: str | None = None) -> dict | None:
    """Test creating customer with phone number."""
    print("--- create_customer (with phone number) ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Use unique name to avoid conflicts
    test_id = uuid.uuid4().hex[:8]
    first_name = f"Test{test_id}"
    last_name = "PhoneUser"
    
    # Use provided phone or generate a test phone
    test_phone = phone or f"+1510555{test_id[:4]}"
    
    # Setmore expects country_code and cell_phone separately
    payload: dict = {
        "first_name": first_name,
        "last_name": last_name,
    }
    
    if test_phone:
        pf = phone_fields(test_phone)
        if pf.get("country_code"):
            payload["country_code"] = pf["country_code"]
        if pf.get("cell_phone"):
            payload["cell_phone"] = pf["cell_phone"]
    
    print(f"Payload: {_pretty(payload)}")
    result = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    print(f"Success: {result.get('success')}")
    
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        print()
        return None
    
    customer = result.get("customer")
    if customer:
        key = customer.get("key")
        first = customer.get("first_name") or ""
        last = customer.get("last_name") or ""
        phone_val = customer.get("cell_phone") or ""
        print(f"Created customer: {first} {last} (key={key}, phone={phone_val})")
        print(f"Full customer data: {_pretty(customer)}")
    else:
        print("WARNING: Customer creation succeeded but customer object is missing!")
        print(f"Full result: {_pretty(result)}")
    print()
    return customer


async def test_create_customer_duplicate(context: dict, first_name: str, last_name: str, phone: str | None = None) -> None:
    """Test creating a duplicate customer (should handle gracefully)."""
    print("--- create_customer (duplicate test) ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    payload: dict = {
        "first_name": first_name,
        "last_name": last_name,
    }
    
    if phone:
        pf = phone_fields(phone)
        if pf.get("country_code"):
            payload["country_code"] = pf["country_code"]
        if pf.get("cell_phone"):
            payload["cell_phone"] = pf["cell_phone"]
    
    print(f"Attempting to create duplicate: {first_name} {last_name}")
    print(f"Payload: {_pretty(payload)}")
    
    # First creation
    result1 = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    print(f"First creation - Success: {result1.get('success')}")
    if result1.get("success"):
        customer1 = result1.get("customer")
        if customer1:
            print(f"First customer key: {customer1.get('key')}")
    
    # Second creation (duplicate)
    result2 = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    print(f"Second creation (duplicate) - Success: {result2.get('success')}")
    if result2.get("success"):
        customer2 = result2.get("customer")
        if customer2:
            print(f"Second customer key: {customer2.get('key')}")
            if customer1 and customer1.get("key") == customer2.get("key"):
                print("✓ Duplicate creation returned same customer (idempotent)")
            else:
                print("⚠ Duplicate creation returned different customer")
    elif not result2.get("success"):
        print(f"Duplicate creation failed (expected): {result2.get('error')}")
    print()


async def test_create_customer_invalid(context: dict) -> None:
    """Test creating customer with invalid data."""
    print("--- create_customer (invalid: missing last_name) ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    payload = {
        "first_name": "Invalid",
        # Missing last_name
    }
    
    print(f"Payload: {_pretty(payload)}")
    result = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    print(f"Success: {result.get('success')} (expected: False)")
    if not result.get("success"):
        print(f"Error (expected): {result.get('error')}")
    else:
        print("⚠ WARNING: Invalid payload was accepted!")
    print()


async def test_lookup_after_create(context: dict, phone: str | None = None) -> None:
    """Test looking up a customer immediately after creation."""
    print("--- lookup_after_create ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Create customer first
    test_id = uuid.uuid4().hex[:8]
    create_first_name = f"LookupTest{test_id}"
    create_last_name = "AfterCreate"
    
    payload: dict = {
        "first_name": create_first_name,
        "last_name": create_last_name,
    }
    
    if phone:
        pf = phone_fields(phone)
        if pf.get("country_code"):
            payload["country_code"] = pf["country_code"]
        if pf.get("cell_phone"):
            payload["cell_phone"] = pf["cell_phone"]
    
    print(f"Creating customer: {create_first_name} {create_last_name}")
    create_result = await setmore_api.create_customer(token, payload, refresh_token=refresh_token)
    
    if not create_result.get("success"):
        print(f"Failed to create customer: {create_result.get('error')}")
        print()
        return
    
    created_customer = create_result.get("customer")
    if not created_customer:
        print("Customer creation succeeded but customer object missing")
        print()
        return
    
    created_key = created_customer.get("key")
    print(f"Created customer key: {created_key}")
    
    # Wait a moment for API to index
    await asyncio.sleep(1)
    
    # Try to lookup
    print(f"Looking up customer by first_name='{create_first_name}'")
    lookup_result = await setmore_api.fetch_customer(
        token, first_name=create_first_name, refresh_token=refresh_token
    )
    
    if lookup_result.get("success"):
        customers = lookup_result.get("customers") or []
        found = None
        for cust in customers:
            if cust.get("key") == created_key:
                found = cust
                break
        
        if found:
            print(f"✓ Successfully found created customer (key={created_key})")
        else:
            print(f"⚠ Created customer not found in lookup results (may need time to index)")
            print(f"Found {len(customers)} customers with first_name='{create_first_name}'")
    else:
        print(f"Lookup failed: {lookup_result.get('error')}")
    print()


async def cleanup_test_customers(context: dict, test_prefix: str = "Test") -> None:
    """Clean up test customers created during testing."""
    print(f"--- cleanup_test_customers (prefix='{test_prefix}') ---")
    token = context["accessToken"]
    refresh_token = context.get("refreshToken") or context.get("refresh_token")
    
    # Fetch all customers with test prefix
    result = await setmore_api.fetch_customer(token, first_name=test_prefix, refresh_token=refresh_token)
    if not result.get("success"):
        print(f"Cannot fetch customers for cleanup: {result.get('error')}")
        return
    
    customers = result.get("customers") or []
    test_customers = [c for c in customers if (c.get("first_name") or "").startswith(test_prefix)]
    
    print(f"Found {len(test_customers)} test customers to clean up")
    print("Note: Setmore API doesn't provide a delete endpoint, so customers will remain in the system.")
    print("They can be manually deleted from the Setmore dashboard if needed.")
    print()


ALL_TESTS = {
    "fetch-customer": test_fetch_customer_by_name,
    "fetch-customer-phone": test_fetch_customer_by_name_and_phone,
    "create-customer-minimal": test_create_customer_minimal,
    "create-customer-phone": test_create_customer_with_phone,
    "create-customer-duplicate": test_create_customer_duplicate,
    "create-customer-invalid": test_create_customer_invalid,
    "lookup-after-create": test_lookup_after_create,
}


async def main(args: argparse.Namespace) -> int:
    print(f"=== Setmore Customer API tests for: {BUSINESS_NUMBER} ===\n")
    context = await _resolve_context()
    print(f"Provider: {context.get('provider')}")
    print(f"Business: {(context.get('location') or {}).get('business_name')}\n")

    tests_to_run = [args.test] if args.test else list(ALL_TESTS.keys())

    created_customers = []

    for test_name in tests_to_run:
        fn = ALL_TESTS.get(test_name)
        if not fn:
            print(f"Unknown test: {test_name}")
            continue
        try:
            if test_name == "fetch-customer":
                first_name = args.first_name or "Test"
                await fn(context, first_name)
            elif test_name == "fetch-customer-phone":
                first_name = args.first_name or "Test"
                phone = args.phone or "+15105551234"
                await fn(context, first_name, phone)
            elif test_name == "create-customer-minimal":
                customer = await fn(context)
                if customer:
                    created_customers.append(customer)
            elif test_name == "create-customer-phone":
                phone = args.phone
                customer = await fn(context, phone)
                if customer:
                    created_customers.append(customer)
            elif test_name == "create-customer-duplicate":
                first_name = args.first_name or f"DuplicateTest{uuid.uuid4().hex[:8]}"
                last_name = args.last_name or "User"
                phone = args.phone
                await fn(context, first_name, last_name, phone)
            elif test_name == "lookup-after-create":
                phone = args.phone
                await fn(context, phone)
            else:
                await fn(context)
        except Exception as exc:
            print(f"ERROR in {test_name}: {exc}")
            import traceback
            traceback.print_exc()

    if args.cleanup and created_customers:
        await cleanup_test_customers(context)

    print("=== Setmore Customer API tests complete ===")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test Setmore Customer APIs for 510 405 4454")
    parser.add_argument(
        "--test",
        choices=list(ALL_TESTS.keys()) + ["all"],
        default="all",
        help="Run a specific test (default: all).",
    )
    parser.add_argument("--first-name", default=None, help="First name for fetch/create tests.")
    parser.add_argument("--last-name", default=None, help="Last name for create tests.")
    parser.add_argument("--phone", default=None, help="Phone number for fetch/create tests.")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test customers after tests.")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    if args.test == "all":
        args.test = None  # Run all tests
    raise SystemExit(asyncio.run(main(args)))
