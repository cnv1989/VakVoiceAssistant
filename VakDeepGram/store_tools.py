"""
Store Tools Configuration for Deepgram Voice Agent
Defines function schemas and implementations for store operations
"""
import logging
from typing import Any, Dict

from square import AsyncSquare
try:
    from square.environment import SquareEnvironment
except Exception:  # pragma: no cover - optional dependency behavior
    SquareEnvironment = None

import config
from connection_store import get_connection_context

logger = logging.getLogger(__name__)


def _square_environment():
    logger.debug("store_tools._square_environment called")
    env_name = config.settings.square_environment
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if env_name == "sandbox" else SquareEnvironment.PRODUCTION
    return "sandbox" if env_name == "sandbox" else "production"


def _get_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools._get_context called (keys=%s)", list(params.keys()))
    connection_id = params.get("connection_id")
    if not connection_id:
        return {"success": False, "error": "connection_id is required", "context": {}}
    context = get_connection_context(connection_id)
    if not context:
        return {"success": False, "error": "No connection context found.", "context": {}}
    return {"success": True, "context": context}


def get_store_location_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_store_location_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "location": {}}
    location = context_result["context"].get("location") or {}
    return {"success": True, "location": location}


def get_store_hours_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_store_hours_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "hours": []}
    location = context_result["context"].get("location") or {}
    business_hours = location.get("business_hours") or {}
    periods = business_hours.get("periods") or []
    return {"success": True, "hours": periods}


def get_services_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_services_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "services": []}
    services = context_result["context"].get("services") or []
    formatted = []
    for item in services:
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
        formatted.append(
            {
                "name": name,
                "description": description,
                "variations": variations,
            }
        )
    return {"success": True, "services": formatted}


def get_staff_from_context(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_staff_from_context called")
    context_result = _get_context(params)
    if not context_result.get("success"):
        return {"success": False, "error": context_result.get("error"), "staff": []}
    staff = context_result["context"].get("staff") or []
    formatted = []
    for member in staff:
        formatted.append(
            {
                "display_name": member.get("display_name"),
                "given_name": member.get("given_name"),
                "family_name": member.get("family_name"),
                "job_title": member.get("job_title"),
                "status": member.get("status"),
            }
        )
    return {"success": True, "staff": formatted}

async def get_store_hours_from_square(params: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("store_tools.get_store_hours_from_square called (keys=%s)", list(params.keys()))
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
    client = AsyncSquare(token=access_token, environment=_square_environment())

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
    logger.debug("Square location response keys: %s", list(location.keys()))
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
