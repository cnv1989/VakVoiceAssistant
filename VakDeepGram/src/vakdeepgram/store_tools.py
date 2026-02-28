"""
Store Tools Configuration for Deepgram Voice Agent
Defines function schemas and implementations for store operations
"""
import logging
from datetime import datetime
from typing import Any, Dict

from square import AsyncSquare

from vakdeepgram.connection_store import get_connection_context
from utils.square_client import get_square_client

logger = logging.getLogger(__name__)

_DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_DAY_LABEL = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
    "SUN": "Sunday",
}


def _to_12h(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return value


def _hours_summary(by_day: list[dict]) -> str:
    open_days = [d for d in by_day if not d.get("closed")]
    closed_days = [d for d in by_day if d.get("closed")]
    if not open_days:
        return "We are currently closed all week."
    first = open_days[0]
    same_window = all(
        d.get("open") == first.get("open") and d.get("close") == first.get("close")
        for d in open_days
    )
    if len(open_days) == 6 and len(closed_days) == 1 and same_window and closed_days[0].get("day_code") == "SUN":
        return (
            f"We are open Monday through Saturday from {first.get('open')} to "
            f"{first.get('close')}, and closed Sunday."
        )
    parts = []
    for d in by_day:
        if d.get("closed"):
            parts.append(f"{d.get('day')}: Closed")
        else:
            parts.append(f"{d.get('day')}: {d.get('open')}-{d.get('close')}")
    return "; ".join(parts)


def _normalize_hours(location: Dict[str, Any]) -> tuple[list[dict], str]:
    # Setmore structured format populated by resolve_business_context
    business_hours = location.get("business_hours") or {}
    if isinstance(business_hours, dict) and isinstance(business_hours.get("by_day"), list):
        by_day = []
        for row in business_hours.get("by_day") or []:
            open_12h = _to_12h(row.get("open"))
            close_12h = _to_12h(row.get("close"))
            by_day.append(
                {
                    "day_code": row.get("day_code"),
                    "day": row.get("day"),
                    "open": open_12h,
                    "close": close_12h,
                    "closed": bool(row.get("closed")),
                }
            )
        summary = location.get("business_hours_text") or _hours_summary(by_day)
        return by_day, summary

    # Square business_hours.periods format
    periods = business_hours.get("periods") if isinstance(business_hours, dict) else []
    by_code = {code: {"day_code": code, "day": _DAY_LABEL[code], "open": None, "close": None, "closed": True} for code in _DAY_ORDER}
    for period in periods or []:
        day_code = period.get("day_of_week")
        if day_code not in by_code:
            continue
        open_local = _to_12h(period.get("start_local_time"))
        close_local = _to_12h(period.get("end_local_time"))
        by_code[day_code] = {
            "day_code": day_code,
            "day": _DAY_LABEL[day_code],
            "open": open_local,
            "close": close_local,
            "closed": False if open_local and close_local else True,
        }
    by_day = [by_code[code] for code in _DAY_ORDER]
    return by_day, _hours_summary(by_day)


def _get_context(params: Dict[str, Any]) -> Dict[str, Any]:
    """Get context from params - supports both voice (connection_id) and chat (business_context) modes."""
    logger.debug("store_tools._get_context called (keys=%s)", list(params.keys()))

    # For chat/SMS, business_context is passed directly from tools
    business_context = params.get("business_context")
    if business_context:
        logger.debug("Using business context passed directly (chat/SMS mode)")
        return {"success": True, "context": business_context}

    # For voice assistant, use connection store
    connection_id = params.get("connection_id")
    if connection_id:
        context = get_connection_context(connection_id)
        if context:
            return {"success": True, "context": context}
        return {"success": False, "error": "No connection context found.", "context": {}}

    return {"success": False, "error": "No business_context or connection_id provided.", "context": {}}


def get_store_location_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_store_location_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "location": {}}
    ctx = context_result["context"]
    location = ctx.get("location") or {}
    provider = ctx.get("provider") or "square"

    if provider == "setmore":
        # Build a rich location response from account info stored in DynamoDB
        return {
            "success": True,
            "location": {
                "business_name": location.get("business_name"),
                "phone_number": location.get("phone_number"),
                "address": location.get("address"),
                "email": location.get("email"),
                "timezone": location.get("timezone"),
                "business_number": ctx.get("businessNumber"),
                "forwarding_number": ctx.get("forwardingNumber"),
                "booking_page_url": ctx.get("bookingPageUrl"),
            },
        }

    # Square — location already has a rich structure from the API
    return {"success": True, "location": location}


def get_store_hours_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_store_hours_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "hours": [], "by_day": [], "human_summary": ""}
    location = context_result["context"].get("location") or {}
    by_day, summary = _normalize_hours(location)
    hours = [
        {
            "day": row["day"],
            "open": row["open"],
            "close": row["close"],
            "closed": row["closed"],
        }
        for row in by_day
    ]
    return {"success": True, "hours": hours, "by_day": by_day, "human_summary": summary}


def get_services_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    """Get services from context - handles both full Square format and optimized format."""
    logger.debug("store_tools.get_services_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "services": []}
    services = context_result["context"].get("services") or []
    formatted = []
    for item in services:
        # Check if this is optimized format (flat variations array) or full Square format
        if "item_data" in item:
            # Full Square format - nested structure
            item_data = item.get("item_data") or {}
            name = item_data.get("name") or item.get("name")
            description = item_data.get("description")
            variations = []
            for variation in item_data.get("variations") or []:
                variation_data = variation.get("item_variation_data") or {}
                price_money = variation_data.get("price_money") or {}
                variations.append(
                    {
                        "name": variation_data.get("name"),
                        "price": price_money.get("amount"),
                        "currency": price_money.get("currency"),
                    }
                )
        else:
            # Optimized format - flat structure with pre-converted fields
            name = item.get("name")
            description = item.get("description")
            variations = []
            for variation in item.get("variations") or []:
                price = variation.get("price") or {}
                variations.append(
                    {
                        "name": variation.get("name"),
                        "price": price.get("amount") if isinstance(price, dict) else None,
                        "currency": price.get("currency") if isinstance(price, dict) else None,
                    }
                )
        formatted.append(
            {
                "name": name,
                "description": description,
                "variations": variations,
            }
        )
    return {"success": True, "services": formatted}


def get_staff_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    """Get staff from context - handles both full Square format and optimized format."""
    logger.debug("store_tools.get_staff_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "staff": []}
    staff = context_result["context"].get("staff") or []
    formatted = []
    for member in staff:
        # Get display_name, computing from given_name/family_name if needed
        display_name = member.get("display_name")
        if not display_name:
            parts = [member.get("given_name"), member.get("family_name")]
            display_name = " ".join(p for p in parts if p).strip() or None
        formatted.append(
            {
                "id": member.get("id"),
                "display_name": display_name,
                "status": member.get("status"),
            }
        )
    return {"success": True, "staff": formatted}

async def get_store_hours_from_square(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("store_tools.get_store_hours_from_square called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}

    context = get_connection_context(connection_id)
    access_token = context.get("accessToken") or context.get("access_token")
    location_id = context.get("locationId")
    if not access_token or not location_id:
        logger.warning(
            "Missing Square auth context for %s (locationId=%s, token=%s)",
            connection_id,
            location_id,
            bool(access_token),
        )
        return {"success": False, "error": "Missing Square access token or location ID."}

    logger.info("Fetching Square location for connection %s (locationId=%s)", connection_id, location_id)
    client = get_square_client(access_token)

    response = await client.locations.get(location_id)
    if hasattr(response, "is_error"):
        if response.is_error():
            logger.error("Square location lookup failed for %s: %s", location_id, response.errors)
            return {"success": False, "error": response.errors}
        payload = response.body or {}
    elif hasattr(response, "model_dump"):
        payload = response.model_dump()
        if payload.get("errors"):
            logger.error("Square location lookup failed for %s: %s", location_id, payload.get("errors"))
            return {"success": False, "error": payload.get("errors")}
    elif isinstance(response, dict):
        payload = response
        if payload.get("errors"):
            logger.error("Square location lookup failed for %s: %s", location_id, payload.get("errors"))
            return {"success": False, "error": payload.get("errors")}
    else:
        logger.error("Square location lookup returned unexpected response type: %s", type(response))
        return {"success": False, "error": "Unexpected Square response type."}

    location = payload.get("location", {})
    logger.info("Square location response keys: %s", list(location.keys()))
    logger.info("Square location fetched: %s (%s)", location.get("name"), location.get("id"))
    business_hours = location.get("business_hours", {}).get("periods", [])
    return {
        "success": True,
        "location": {
            "id": location.get("id"),
            "name": location.get("name"),
            "phone_number": location.get("phone_number"),
            "timezone": location.get("timezone"),
            "address": location.get("address"),
            "business_hours": business_hours,
        },
    }
