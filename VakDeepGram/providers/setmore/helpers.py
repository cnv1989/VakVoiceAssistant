"""
Setmore-specific helpers.

Service matching, staff resolution, date formatting, slot conversion,
and booking URL construction.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]

from utils.phone import normalize_phone_number

logger = logging.getLogger(__name__)


# ── Service / staff resolution ────────────────────────────────────────────────

def match_service(business_context: dict, service_name: str) -> Optional[dict]:
    """Match a service name (exact then partial) from context services list."""
    services = business_context.get("services") or []
    target = service_name.strip().lower()
    # Exact match first
    for svc in services:
        name = (svc.get("name") or "").strip().lower()
        if name == target:
            return svc
    # Partial: target contains service name or service name contains target
    for svc in services:
        name = (svc.get("name") or "").strip().lower()
        if not name:
            continue
        if target in name or name in target:
            return svc
    return None


def resolve_staff_key(
    business_context: dict,
    staff_ids: list[str] | None = None,
) -> Optional[str]:
    """Resolve a Setmore staff key from requested IDs or return first available."""
    staff = business_context.get("staff") or []
    if staff_ids:
        for req in staff_ids:
            if not req:
                continue
            req_lower = req.strip().lower()
            for member in staff:
                mid = member.get("id") or ""
                name = f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
                if req_lower in (mid.lower(), name.lower()):
                    return mid
    # Default to first staff member
    return staff[0].get("id") if staff else None


def staff_display_name(business_context: dict, staff_key: Optional[str]) -> Optional[str]:
    """Get a human-readable name for a staff key."""
    if not staff_key:
        return None
    for member in business_context.get("staff") or []:
        if member.get("id") == staff_key:
            first = member.get("first_name") or ""
            last = member.get("last_name") or ""
            return f"{first} {last}".strip() or None
    return None


# ── Date formatting ───────────────────────────────────────────────────────────

def format_date(dt: datetime) -> str:
    """Format datetime as DD/MM/YYYY for Setmore slots API."""
    return dt.strftime("%d/%m/%Y")


def slot_to_iso(base_date: datetime, slot_str: str, tzinfo: Any = None) -> Optional[str]:
    """Convert a Setmore slot string to ISO datetime.

    Supports:
      - "09:00 - 09:45" (start - end)
      - "9:00 AM", "2:00 PM", "12:00 PM" (12-hour format from API)
    """
    try:
        # Take start time only if in "HH:MM - HH:MM" form
        raw = slot_str.strip()
        if " - " in raw:
            raw = raw.split(" - ")[0].strip()
        # Normalize 12-hour format: "9:00 AM" / "2:00 PM" / "12:00 PM"
        raw_upper = raw.upper()
        if " AM" in raw_upper or " PM" in raw_upper:
            is_pm = " PM" in raw_upper
            time_part = raw_upper.replace(" AM", "").replace(" PM", "").strip()
            parts = time_part.split(":")
            hour = int(parts[0].strip())
            minute = int(parts[1].strip()) if len(parts) > 1 else 0
            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0
        else:
            # "09:00" or "9:00"
            parts = raw.split(":")
            hour = int(parts[0].strip())
            minute = int(parts[1].strip()) if len(parts) > 1 else 0
        dt = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tzinfo:
            dt = dt.replace(tzinfo=tzinfo)
        return dt.isoformat()
    except Exception:
        return None


# ── Phone helpers ─────────────────────────────────────────────────────────────

def phone_fields(phone_number: Optional[str]) -> Dict[str, Optional[str]]:
    """Split a phone number into country_code and cell_phone for Setmore API.
    
    Setmore expects:
    - country_code: "+1" for US numbers
    - cell_phone: 10-digit number without country code (e.g., "5105551234")
    
    Returns dict with country_code and cell_phone keys.
    """
    if not phone_number:
        return {"country_code": None, "cell_phone": None}
    normalized = normalize_phone_number(phone_number) or phone_number
    
    # Handle US numbers (+1XXXXXXXXXX or 1XXXXXXXXXX)
    if normalized.startswith("+1") and len(normalized) == 12:
        # +15105551234 -> country_code: "+1", cell_phone: "5105551234"
        return {"country_code": "+1", "cell_phone": normalized[2:]}
    elif normalized.startswith("1") and len(normalized) == 11:
        # 15105551234 -> country_code: "+1", cell_phone: "5105551234"
        return {"country_code": "+1", "cell_phone": normalized[1:]}
    elif len(normalized) == 10 and normalized.isdigit():
        # 5105551234 -> country_code: None, cell_phone: "5105551234"
        return {"country_code": None, "cell_phone": normalized}
    elif normalized.startswith("+") and len(normalized) > 2:
        # Other country codes: extract country code (2-3 chars) and rest as cell_phone
        if normalized.startswith("+1"):
            country_code = "+1"
            cell_phone = normalized[2:] if len(normalized) > 2 else normalized
        else:
            # For non-US, try to extract 3-char country code
            country_code = normalized[:3] if len(normalized) > 3 else normalized[:2]
            cell_phone = normalized[len(country_code):]
        return {"country_code": country_code, "cell_phone": cell_phone}
    
    # Fallback: return as-is without country code
    return {"country_code": None, "cell_phone": normalized}


# ── Booking URL helpers ───────────────────────────────────────────────────────

def normalize_booking_url(raw: str) -> str:
    """Ensure the booking page URL is a full https://…setmore.com URL.

    Accepts:
      - Full URL:       https://mybiz.setmore.com  →  as-is
      - Missing scheme: mybiz.setmore.com          →  https://mybiz.setmore.com
      - Bare slug:      mybiz                      →  https://mybiz.setmore.com
    """
    val = raw.strip().rstrip("/")
    if not val:
        return val
    if re.match(r"^https?://", val, re.IGNORECASE):
        return val
    if ".setmore.com" in val.lower():
        return f"https://{val}"
    return f"https://{val}.setmore.com"


def build_booking_url(
    booking_page_url: str,
    service_key: Optional[str] = None,
    staff_key: Optional[str] = None,
    start_dt: Optional[datetime] = None,
    customer_key: Optional[str] = None,
) -> str:
    """Build a Setmore booking URL with prefilled query parameters.

    Setmore booking pages accept:
        step=payment, products=<service>, type=service,
        staff=<staff>, slot=<epoch_ms>, customer=<customer>
    """
    normalized = normalize_booking_url(booking_page_url)
    parsed = urlparse(normalized.rstrip("/"))
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    if not path.endswith("/book"):
        path = f"{path}/book" if path else "/book"

    params: Dict[str, str] = {"step": "user-details", "type": "service"}
    if service_key:
        params["products"] = service_key
    if staff_key:
        params["staff"] = staff_key
        params["staffSelected"] = "true"
    if start_dt:
        epoch_ms = int(start_dt.timestamp() * 1000)
        params["slot"] = str(epoch_ms)
    if customer_key:
        params["customer"] = customer_key

    return f"{base}{path}?{urlencode(params)}"
