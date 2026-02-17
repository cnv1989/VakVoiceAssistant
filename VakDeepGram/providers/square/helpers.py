"""
Square-specific helpers.

Client creation, customer lookup, and availability formatting.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from square import AsyncSquare

from utils.square_client import get_square_client
from utils.phone import normalize_phone_number, phone_digit_variants
from providers.common.helpers import as_dict
from utils.metrics import emit_api_metrics

logger = logging.getLogger(__name__)


def get_client(access_token: str) -> AsyncSquare:
    """Return a Square client (pooled, with exponential backoff retries)."""
    return get_square_client(access_token)


def get_access_context(business_context: dict) -> dict:
    """Validate and extract access_token + location_id from context."""
    access_token = business_context.get("accessToken") or business_context.get("access_token")
    location_id = business_context.get("locationId") or business_context.get("location_id")
    if not access_token:
        return {"success": False, "error": "Missing Square access token."}
    if not location_id:
        return {"success": False, "error": "Missing Square location ID."}
    return {"success": True, "access_token": access_token, "location_id": location_id}


async def find_customer_by_phone(client: AsyncSquare, phone: str) -> Optional[dict]:
    """Search for a Square customer by phone number (tries digit variants)."""
    variants = phone_digit_variants(phone) or [phone]
    for variant in variants:
        start = time.monotonic()
        try:
            result = await client.customers.search(
                query={"filter": {"phone_number": {"exact": variant}}}
            )
            emit_api_metrics("square", "customers.search", (time.monotonic() - start) * 1000, True)
            parsed = as_dict(result)
            if isinstance(parsed, dict):
                customers = parsed.get("customers") or []
            else:
                customers = getattr(result, "customers", None) or []
            if customers:
                return as_dict(customers[0])
        except Exception:
            emit_api_metrics(
                "square",
                "customers.search",
                (time.monotonic() - start) * 1000,
                False,
                error_type="Exception",
            )
            continue
    return None


async def collect_async_pager(pager) -> list[dict]:
    """Collect items from a Square async pager into a list."""
    items: list[dict] = []
    async for item in pager:
        items.append(as_dict(item))
    return items
