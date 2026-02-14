"""
Utilities for optimizing Square API responses for minimal token usage.
Extracts only essential fields needed for voice agent operations.
"""
from typing import Any, Dict, List, Optional


def optimize_location(location: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract minimal location fields.

    Keeps: id, name, business_name, timezone, phone_number, simplified address and business_hours.
    """
    if not location:
        return None

    address = location.get("address") or {}
    business_hours = location.get("business_hours") or {}

    optimized = {
        "id": location.get("id"),
        "name": location.get("name"),
        "business_name": location.get("business_name"),
        "timezone": location.get("timezone"),
        "phone_number": location.get("phone_number"),
    }

    # Simplified address (only essential fields)
    if address:
        optimized["address"] = {
            "address_line_1": address.get("address_line_1"),
            "locality": address.get("locality"),
            "administrative_district_level_1": address.get("administrative_district_level_1"),
            "postal_code": address.get("postal_code"),
        }

    # Simplified business hours (only day and times)
    periods = business_hours.get("periods") or []
    if periods:
        optimized["business_hours"] = {
            "periods": [
                {
                    "day_of_week": p.get("day_of_week"),
                    "start_local_time": p.get("start_local_time"),
                    "end_local_time": p.get("end_local_time"),
                }
                for p in periods
            ]
        }

    return optimized


def optimize_services(services: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Extract minimal service fields with duration converted to minutes.

    Keeps per item: id, name
    Keeps per variation: id, name, duration_minutes, version, price
    """
    if not services:
        return []

    optimized = []
    for item in services:
        item_data = item.get("item_data") or {}
        item_name = item_data.get("name") or item.get("name")

        variations = []
        for var in item_data.get("variations") or []:
            var_data = var.get("item_variation_data") or {}
            price_money = var_data.get("price_money") or {}
            duration_ms = var_data.get("service_duration")

            variation = {
                "id": var.get("id"),
                "name": var_data.get("name"),
                "duration_minutes": int(duration_ms / 60000) if duration_ms else None,
                "version": var.get("version"),
            }

            # Only include price if present
            if price_money.get("amount") is not None:
                variation["price"] = {
                    "amount": price_money.get("amount"),
                    "currency": price_money.get("currency"),
                }

            variations.append(variation)

        optimized.append({
            "id": item.get("id"),
            "name": item_name,
            "variations": variations,
        })

    return optimized


def optimize_staff(staff: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Extract minimal staff fields with computed display_name.

    Keeps: id, status, display_name (computed from given_name/family_name if not present)
    """
    if not staff:
        return []

    optimized = []
    for member in staff:
        display_name = member.get("display_name")
        if not display_name:
            parts = [member.get("given_name"), member.get("family_name")]
            display_name = " ".join(p for p in parts if p).strip() or None

        optimized.append({
            "id": member.get("id"),
            "status": member.get("status"),
            "display_name": display_name,
        })

    return optimized


def optimize_bookings(bookings_result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract minimal booking fields.

    Keeps per booking: id, status, start_at, customer_id, location_id, version
    Keeps first segment only: service_variation_id, team_member_id, duration_minutes
    """
    if not bookings_result:
        return None

    if not bookings_result.get("success"):
        return bookings_result

    optimized_bookings = []
    for booking in bookings_result.get("bookings") or []:
        # Handle both dict and object formats
        if hasattr(booking, "model_dump"):
            booking = booking.model_dump()

        segments = booking.get("appointment_segments") or booking.get("appointmentSegments") or []
        segment = segments[0] if segments else {}

        # Handle segment as dict or object
        if hasattr(segment, "model_dump"):
            segment = segment.model_dump()

        optimized_booking = {
            "id": booking.get("id"),
            "status": booking.get("status"),
            "start_at": booking.get("start_at") or booking.get("startAt"),
            "customer_id": booking.get("customer_id") or booking.get("customerId"),
            "location_id": booking.get("location_id") or booking.get("locationId"),
            "version": booking.get("version"),
        }

        if segment:
            optimized_booking["segment"] = {
                "service_variation_id": segment.get("service_variation_id") or segment.get("serviceVariationId"),
                "team_member_id": segment.get("team_member_id") or segment.get("teamMemberId"),
                "duration_minutes": segment.get("duration_minutes") or segment.get("durationMinutes"),
            }

        optimized_bookings.append(optimized_booking)

    return {
        "success": True,
        "bookings": optimized_bookings,
        "start_at_min": bookings_result.get("start_at_min"),
        "start_at_max": bookings_result.get("start_at_max"),
    }


def optimize_customer(customer: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract minimal customer fields.

    Keeps: id, given_name, family_name, phone_number
    """
    if not customer:
        return None

    # Handle object format
    if hasattr(customer, "model_dump"):
        customer = customer.model_dump()

    return {
        "id": customer.get("id"),
        "given_name": customer.get("given_name") or customer.get("givenName"),
        "family_name": customer.get("family_name") or customer.get("familyName"),
        "phone_number": customer.get("phone_number") or customer.get("phoneNumber"),
    }

