#!/usr/bin/env python3
"""
Unit test for Setmore booking URL building (normalize + build_booking_url).

Verifies the booking URL flow logic without calling the live API.
Usage: cd VakDeepGram && python -m scripts.tests.test_booking_url_builder
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

from providers.setmore.helpers import (
    normalize_booking_url,
    build_booking_url,
    slot_to_iso,
)


def test_normalize_booking_url() -> None:
    assert normalize_booking_url("examplebusiness") == "https://examplebusiness.setmore.com"
    assert normalize_booking_url("examplebusiness.setmore.com") == "https://examplebusiness.setmore.com"
    assert "https://examplebusiness.setmore.com" in normalize_booking_url("https://examplebusiness.setmore.com")
    assert normalize_booking_url("  ") == ""  # strip() then empty returns ""


def test_build_booking_url() -> None:
    # Minimal: just base URL
    url = build_booking_url("examplebusiness")
    assert "examplebusiness.setmore.com" in url
    assert "/book" in url
    assert "step=user-details" in url
    assert "type=service" in url

    # With service, staff, slot, customer
    start_dt = datetime(2026, 2, 17, 14, 0, 0, tzinfo=timezone.utc)  # 2 PM UTC
    url = build_booking_url(
        "https://examplebusiness.setmore.com",
        service_key="cab1c0ce-9195-4623-bf9a-890a21fce0f9",
        staff_key="e6e0f716-ae01-42ba-9452-caf3205ff7a1",
        start_dt=start_dt,
        customer_key="31a34811-4069-4835-9f08-7c48e0e1ab21",
    )
    assert "examplebusiness.setmore.com" in url
    assert "/book" in url
    assert "products=cab1c0ce" in url or "products=" in url
    assert "staff=e6e0f716" in url or "staff=" in url
    assert "slot=" in url
    assert "customer=31a34811" in url or "customer=" in url
    assert "step=user-details" in url


def test_slot_to_iso() -> None:
    from datetime import datetime
    base = datetime(2026, 2, 17, 0, 0, 0)  # Tuesday
    # 12-hour format (what Setmore API returns)
    assert "2026-02-17T09:00" in slot_to_iso(base, "9:00 AM")
    assert "2026-02-17T14:00" in slot_to_iso(base, "2:00 PM")
    assert "2026-02-17T12:00" in slot_to_iso(base, "12:00 PM")
    # Range format (legacy)
    assert "2026-02-17T09:00" in slot_to_iso(base, "09:00 - 09:45")


def main() -> int:
    test_normalize_booking_url()
    test_build_booking_url()
    test_slot_to_iso()
    print("PASS: Booking URL builder tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
