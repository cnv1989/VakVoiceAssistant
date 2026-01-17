"""
Helpers for resolving business context from DynamoDB for Square integrations.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import aioboto3
from square import AsyncSquare
try:
    from square.environment import SquareEnvironment
except Exception:  # pragma: no cover - optional dependency behavior
    SquareEnvironment = None

import config

logger = logging.getLogger(__name__)

_connection_contexts: Dict[str, Dict[str, Any]] = {}
_SERVICE_PRODUCT_TYPES = ["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"]


def set_connection_context(connection_id: str, context: Dict[str, Any]) -> None:
    _connection_contexts[connection_id] = context


def get_connection_context(connection_id: str) -> Dict[str, Any]:
    return _connection_contexts.get(connection_id, {})


def clear_connection_context(connection_id: str) -> None:
    _connection_contexts.pop(connection_id, None)


def normalize_phone_number(value: str) -> Optional[str]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("1") and len(digits) == 11:
        normalized = f"+{digits}"
        logger.debug("Normalized phone number %s -> %s", value, normalized)
        return normalized
    if len(digits) == 10:
        normalized = f"+1{digits}"
        logger.debug("Normalized phone number %s -> %s", value, normalized)
        return normalized
    if value.startswith("+"):
        logger.debug("Normalized phone number %s -> %s", value, value)
        return value
    normalized = f"+{digits}"
    logger.debug("Normalized phone number %s -> %s", value, normalized)
    return normalized


def _square_environment():
    env_name = config.settings.square_environment
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if env_name == "sandbox" else SquareEnvironment.PRODUCTION
    return "sandbox" if env_name == "sandbox" else "production"


async def _fetch_business_number_record(phone_number: str) -> Optional[Dict[str, Any]]:
    logger.info("Fetching BusinessNumber record for %s", phone_number)
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=config.settings.aws_region) as dynamodb:
        table = dynamodb.Table(config.settings.business_number_table)
        if asyncio.iscoroutine(table):
            table = await table
        response = await table.get_item(Key={"phoneNumber": phone_number})
        return response.get("Item")


async def _fetch_square_account_record(user_id: str, merchant_id: str) -> Optional[Dict[str, Any]]:
    logger.info("Fetching SquareAccount record for userId=%s merchantId=%s", user_id, merchant_id)
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=config.settings.aws_region) as dynamodb:
        table = dynamodb.Table(config.settings.square_account_table)
        if asyncio.iscoroutine(table):
            table = await table
        response = await table.get_item(Key={"userId": user_id, "merchantId": merchant_id})
        return response.get("Item")


async def _fetch_square_location(access_token: str, location_id: str) -> Dict[str, Any]:
    logger.info("Fetching Square location %s", location_id)
    client = AsyncSquare(token=access_token, environment=_square_environment())
    response = await client.locations.get(location_id)
    if hasattr(response, "is_error"):
        if response.is_error():
            return {"success": False, "error": response.errors}
        payload = response.body or {}
    elif hasattr(response, "model_dump"):
        payload = response.model_dump()
        if payload.get("errors"):
            return {"success": False, "error": payload.get("errors")}
    elif isinstance(response, dict):
        payload = response
        if payload.get("errors"):
            return {"success": False, "error": payload.get("errors")}
    else:
        return {"success": False, "error": "Unexpected Square response type."}
    return {"success": True, "location": payload.get("location", {})}


async def _fetch_square_services(access_token: str, location_id: str) -> Dict[str, Any]:
    logger.info("Fetching Square services for locationId=%s", location_id)
    client = AsyncSquare(token=access_token, environment=_square_environment())
    items: list[Dict[str, Any]] = []
    cursor = None
    while True:
        response = await client.catalog.search_items(
            enabled_location_ids=[location_id],
            product_types=_SERVICE_PRODUCT_TYPES,
            cursor=cursor,
        )
        if hasattr(response, "is_error"):
            if response.is_error():
                return {"success": False, "error": response.errors}
            payload = response.body or {}
        elif hasattr(response, "model_dump"):
            payload = response.model_dump()
            if payload.get("errors"):
                return {"success": False, "error": payload.get("errors")}
        elif isinstance(response, dict):
            payload = response
            if payload.get("errors"):
                return {"success": False, "error": payload.get("errors")}
        else:
            return {"success": False, "error": "Unexpected Square response type."}

        items.extend(payload.get("items") or [])
        cursor = payload.get("cursor")
        if not cursor:
            break

    return {"success": True, "items": items}


async def _fetch_square_staff(access_token: str, location_id: str) -> Dict[str, Any]:
    try:
        from square.types.search_team_members_query import SearchTeamMembersQuery
        from square.types.search_team_members_filter import SearchTeamMembersFilter
    except Exception:
        return {"success": False, "error": "Square team member query types unavailable."}

    logger.info("Fetching Square staff for locationId=%s", location_id)
    client = AsyncSquare(token=access_token, environment=_square_environment())
    team_members: list[Dict[str, Any]] = []
    cursor = None
    while True:
        query = SearchTeamMembersQuery(
            filter=SearchTeamMembersFilter(location_ids=[location_id], status="ACTIVE"),
        )
        response = await client.team_members.search(query=query, limit=200, cursor=cursor)
        if hasattr(response, "is_error"):
            if response.is_error():
                return {"success": False, "error": response.errors}
            payload = response.body or {}
        elif hasattr(response, "model_dump"):
            payload = response.model_dump()
            if payload.get("errors"):
                return {"success": False, "error": payload.get("errors")}
        elif isinstance(response, dict):
            payload = response
            if payload.get("errors"):
                return {"success": False, "error": payload.get("errors")}
        else:
            return {"success": False, "error": "Unexpected Square response type."}

        team_members.extend(payload.get("team_members") or [])
        cursor = payload.get("cursor")
        if not cursor:
            break

    return {"success": True, "team_members": team_members}


def _candidate_numbers(raw_number: str) -> list[str]:
    normalized = normalize_phone_number(raw_number)
    if not normalized:
        return []
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        return [digits[1:]]
    if len(digits) == 10:
        return [digits]
    return [digits]


async def resolve_business_context(business_number: str) -> Dict[str, Any]:
    candidates = _candidate_numbers(business_number)
    if not candidates:
        logger.warning("Business number normalization failed: %s", business_number)
        return {"success": False, "error": "Invalid business number."}

    logger.info("Resolving business context for %s (candidates=%s)", business_number, candidates)
    record = None
    matched_number = None
    for candidate in candidates:
        record = await _fetch_business_number_record(candidate)
        if record:
            matched_number = candidate
            break
        logger.debug("No BusinessNumber record found for %s", candidate)

    if not record:
        logger.warning("No BusinessNumber record found for %s", candidates)
        return {"success": False, "error": "Business number not found."}

    location_id = record.get("locationId") or record.get("location_id")
    merchant_id = record.get("merchantId") or record.get("squareMerchantId")
    user_id = record.get("userId") or record.get("ownerId")

    if not all([location_id, merchant_id, user_id]):
        logger.warning(
            "Business record missing fields for %s (locationId=%s, merchantId=%s, userId=%s)",
            matched_number,
            location_id,
            merchant_id,
            user_id,
        )
        return {
            "success": False,
            "error": "Business record missing locationId, merchantId, or userId.",
        }

    logger.info(
        "Business record found for %s (locationId=%s, merchantId=%s, userId=%s)",
        matched_number,
        location_id,
        merchant_id,
        user_id,
    )
    account = await _fetch_square_account_record(user_id, merchant_id)
    if not account:
        logger.warning(
            "No SquareAccount record for userId=%s merchantId=%s",
            user_id,
            merchant_id,
        )
        return {"success": False, "error": "Square account not found."}

    access_token = account.get("accessToken") or account.get("access_token")
    if not access_token:
        logger.warning("Square account missing access token for userId=%s merchantId=%s", user_id, merchant_id)
        return {"success": False, "error": "Square access token not found."}

    location_result = await _fetch_square_location(access_token, location_id)
    location = location_result.get("location") if location_result.get("success") else None
    if not location:
        logger.warning(
            "Square location lookup failed for locationId=%s: %s",
            location_id,
            location_result.get("error"),
        )

    services_result = await _fetch_square_services(access_token, location_id)
    services = services_result.get("items") if services_result.get("success") else []
    if not services_result.get("success"):
        logger.warning(
            "Square services lookup failed for locationId=%s: %s",
            location_id,
            services_result.get("error"),
        )

    staff_result = await _fetch_square_staff(access_token, location_id)
    staff = staff_result.get("team_members") if staff_result.get("success") else []
    if not staff_result.get("success"):
        logger.warning(
            "Square staff lookup failed for locationId=%s: %s",
            location_id,
            staff_result.get("error"),
        )

    logger.info(
        "Resolved business context for %s (locationId=%s, merchantId=%s, userId=%s)",
        matched_number,
        location_id,
        merchant_id,
        user_id,
    )

    return {
        "success": True,
        "businessNumber": matched_number,
        "locationId": location_id,
        "merchantId": merchant_id,
        "userId": user_id,
        "accessToken": access_token,
        "location": location,
        "services": services,
        "staff": staff,
    }
