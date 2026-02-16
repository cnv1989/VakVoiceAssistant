#!/usr/bin/env python3
"""
Integration test: call Setmore create_appointment tool with real business context.

Resolves context for the test business number, builds a mock ToolContext,
and calls create_appointment to verify it returns a booking_url.

Usage: cd VakDeepGram && python -m scripts.tests.test_booking_url_tool
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def main() -> int:
    from connection_store import resolve_business_context
    from providers.setmore.tools import create_appointment

    business_number = "+15104054454"
    print("Resolving business context ...")
    ctx = await resolve_business_context(business_number)
    if not ctx.get("success"):
        print(f"FAIL: Could not resolve context: {ctx.get('error')}")
        return 1

    # Mock ToolContext so the tool can read business_context
    class MockAgent:
        def __init__(self, state: dict):
            self.state = state

    class MockToolContext:
        def __init__(self, business_context: dict):
            self.agent = MockAgent({"business_context": business_context})

    # Use a service name that likely exists (e.g. first service from context)
    services = ctx.get("services") or []
    service_name = "Regular Haircut"
    if services:
        first_svc = services[0]
        if isinstance(first_svc, dict):
            service_name = first_svc.get("name") or first_svc.get("item_data", {}).get("name") or service_name
        else:
            service_name = getattr(first_svc, "name", None) or getattr(first_svc, "item_data", {}).get("name", service_name)

    # Pass customer_id="" and phone so the tool creates the customer, then creates the appointment
    ctx["caller"] = "+15105796565"
    mock_tc = MockToolContext(ctx)
    print(f"Calling create_appointment (service={service_name}, date=2026-02-20T14:00:00, create customer from phone) ...")
    result = await create_appointment(
        mock_tc,
        first_name="John",
        last_name="Smith",
        customer_id="",
        date="2026-02-20T14:00:00",
        service=service_name,
        staff_id=None,
        phone_number="+15105796565",
        caller_number="+15105796565",
    )

    if not result.get("success"):
        print(f"FAIL: create_appointment returned: {result.get('error')}")
        if result.get("booking_url"):
            print(f"  (fallback booking_url present: {result.get('booking_url')[:70]}...)")
        return 1

    url = result.get("booking_url") or ""
    if "setmore.com" not in url or "/book" not in url:
        print(f"FAIL: booking_url missing or invalid: {url[:80] if url else 'None'}...")
        return 1

    print(f"PASS: create_appointment returned booking_url ({len(url)} chars)")
    print(f"  URL: {url[:90]}...")
    if result.get("appointment_id"):
        print(f"  appointment_id: {result.get('appointment_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
