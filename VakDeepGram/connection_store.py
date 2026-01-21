"""
Helpers for resolving business context from DynamoDB for Square integrations.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import aioboto3
from square import AsyncSquare
try:
    from square.environment import SquareEnvironment
except Exception:  # pragma: no cover - optional dependency behavior
    SquareEnvironment = None
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

import config

logger = logging.getLogger(__name__)

_connection_contexts: Dict[str, Dict[str, Any]] = {}
_SERVICE_PRODUCT_TYPES = ["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"]


def _parse_square_response(response: Any) -> Dict[str, Any]:
    logger.info("connection_store._parse_square_response called (type=%s)", type(response))
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
        return {"success": False, "error": f"Unexpected Square response type: {type(response)}"}
    return {"success": True, "payload": payload}


def _extract_square_cursor(response: Any) -> Optional[str]:
    logger.info("connection_store._extract_square_cursor called (type=%s)", type(response))
    for attr in ("_response", "response", "__response"):
        page = getattr(response, attr, None)
        if page:
            return getattr(page, "cursor", None)
    return None


def set_connection_context(connection_id: str, context: Dict[str, Any]) -> None:
    logger.info("connection_store.set_connection_context called (connection_id=%s)", connection_id)
    _connection_contexts[connection_id] = context


def update_connection_context(connection_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("connection_store.update_connection_context called (connection_id=%s)", connection_id)
    existing = _connection_contexts.get(connection_id, {})
    merged = {**existing, **updates}
    _connection_contexts[connection_id] = merged
    return merged


def get_connection_context(connection_id: str) -> Dict[str, Any]:
    logger.info("connection_store.get_connection_context called (connection_id=%s)", connection_id)
    return _connection_contexts.get(connection_id, {})


def clear_connection_context(connection_id: str) -> None:
    logger.info("connection_store.clear_connection_context called (connection_id=%s)", connection_id)
    _connection_contexts.pop(connection_id, None)


def get_localized_datetime_for_connection(connection_id: str) -> str:
    """Return a localized datetime string based on the connection's location ID."""
    logger.info("connection_store.get_localized_datetime_for_connection called (connection_id=%s)", connection_id)
    context = get_connection_context(connection_id)
    location = context.get("location") or {}
    timezone_name = location.get("timezone") or context.get("timezone")
    now = datetime.now(ZoneInfo(timezone_name)) if timezone_name and ZoneInfo else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S (%A, %B %d, %Y)")


def _isoformat_utc(value: datetime) -> str:
    logger.info("connection_store._isoformat_utc called (value=%s)", value)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _next_four_weeks_range(tz_name: Optional[str]) -> tuple[datetime, datetime]:
    logger.info("connection_store._next_four_weeks_range called (tz=%s)", tz_name)
    tzinfo = ZoneInfo(tz_name) if tz_name and ZoneInfo else None
    now = datetime.now(tzinfo) if tzinfo else datetime.now(timezone.utc)
    start = now
    end = start + timedelta(weeks=4) - timedelta(microseconds=1000)
    return start, end


async def _fetch_square_bookings_for_month(
    access_token: str,
    location_id: str,
    timezone_name: Optional[str],
) -> Dict[str, Any]:
    logger.debug(
        "connection_store._fetch_square_bookings_for_month called (location_id=%s tz=%s)",
        location_id,
        timezone_name,
    )
    start_local, end_local = _next_four_weeks_range(timezone_name)
    start_at_min = _isoformat_utc(start_local)
    start_at_max = _isoformat_utc(end_local)
    logger.debug(
        "Fetching Square bookings for %s (start_at_min=%s start_at_max=%s)",
        location_id,
        start_at_min,
        start_at_max,
    )
    client = AsyncSquare(token=access_token, environment=_square_environment())
    bookings: list[Dict[str, Any]] = []
    cursor = None
    while True:
        response = await client.bookings.list(
            location_id=location_id,
            start_at_min=start_at_min,
            start_at_max=start_at_max,
            cursor=cursor,
            limit=200,
        )
        if hasattr(response, "__aiter__"):
            async for booking in response:
                bookings.append(booking)
            cursor = _extract_square_cursor(response)
            logger.debug("Square bookings iterable page retrieved (cursor=%s)", cursor)
        else:
            parsed = _parse_square_response(response)
            if not parsed.get("success"):
                return {"success": False, "error": parsed.get("error")}
            payload = parsed.get("payload", {})
            bookings.extend(payload.get("bookings") or [])
            cursor = payload.get("cursor")
            logger.debug("Square bookings page retrieved (cursor=%s)", cursor)
        if not cursor:
            break
    logger.debug("Fetched %d Square bookings for %s", len(bookings), location_id)
    return {
        "success": True,
        "bookings": bookings,
        "start_at_min": start_at_min,
        "start_at_max": start_at_max,
    }


def normalize_phone_number(value: str) -> Optional[str]:
    logger.info("connection_store.normalize_phone_number called (value=%s)", value)
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
    logger.info("connection_store._square_environment called")
    env_name = config.settings.square_environment
    if SquareEnvironment:
        return SquareEnvironment.SANDBOX if env_name == "sandbox" else SquareEnvironment.PRODUCTION
    return "sandbox" if env_name == "sandbox" else "production"


async def _fetch_business_number_record(phone_number: str) -> Optional[Dict[str, Any]]:
    logger.info("connection_store._fetch_business_number_record called (phone=%s)", phone_number)
    logger.info("Fetching BusinessNumber record for %s", phone_number)
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=config.settings.aws_region) as dynamodb:
        table = dynamodb.Table(config.settings.business_number_table)
        if asyncio.iscoroutine(table):
            table = await table
        response = await table.get_item(Key={"phoneNumber": phone_number})
        return response.get("Item")


async def _fetch_square_account_record(user_id: str, merchant_id: str) -> Optional[Dict[str, Any]]:
    logger.debug(
        "connection_store._fetch_square_account_record called (user_id=%s merchant_id=%s)",
        user_id,
        merchant_id,
    )
    logger.info("Fetching SquareAccount record for userId=%s merchantId=%s", user_id, merchant_id)
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=config.settings.aws_region) as dynamodb:
        table = dynamodb.Table(config.settings.square_account_table)
        if asyncio.iscoroutine(table):
            table = await table
        response = await table.get_item(Key={"userId": user_id, "merchantId": merchant_id})
        return response.get("Item")


async def _fetch_square_location(access_token: str, location_id: str) -> Dict[str, Any]:
    logger.info("connection_store._fetch_square_location called (location_id=%s)", location_id)
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
    logger.info("connection_store._fetch_square_services called (location_id=%s)", location_id)
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
    logger.info("connection_store._fetch_square_staff called (location_id=%s)", location_id)
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
    logger.info("connection_store._candidate_numbers called (raw=%s)", raw_number)
    normalized = normalize_phone_number(raw_number)
    if not normalized:
        return []
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        return [digits[1:]]
    if len(digits) == 10:
        return [digits]
    return [digits]


def _phone_digits(value: Optional[str]) -> Optional[str]:
    logger.info("connection_store._phone_digits called (value=%s)", value)
    normalized = normalize_phone_number(value or "")
    if not normalized:
        return None
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        return digits[1:]
    return digits


def _phone_digit_variants(value: Optional[str]) -> set[str]:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        normalized = normalize_phone_number(value or "")
        if not normalized:
            return set()
        digits = "".join(ch for ch in normalized if ch.isdigit())
    variants = {digits} if digits else set()
    if digits.startswith("1") and len(digits) == 11:
        variants.add(digits[1:])
    if len(digits) == 10:
        variants.add(f"1{digits}")
    return variants


async def _fetch_square_customers(access_token: str) -> Dict[str, Any]:
    logger.info("connection_store._fetch_square_customers called")
    logger.info("Fetching Square customers")
    client = AsyncSquare(token=access_token, environment=_square_environment())
    customers: list[Dict[str, Any]] = []
    cursor = None
    while True:
        response = await client.customers.list(cursor=cursor, limit=100)
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

        customers.extend(payload.get("customers") or [])
        cursor = payload.get("cursor")
        if not cursor:
            break

    return {"success": True, "customers": customers}


async def fetch_square_customer_by_phone(access_token: str, phone_number: str) -> Dict[str, Any]:
    logger.info("connection_store.fetch_square_customer_by_phone called (phone=%s)", phone_number)
    candidate_digits = _phone_digit_variants(phone_number)
    if not candidate_digits:
        return {"success": False, "error": "Invalid phone number."}

    result = await _fetch_square_customers(access_token)
    if not result.get("success"):
        return result

    for customer in result.get("customers") or []:
        customer_phone = customer.get("phone_number") or customer.get("phoneNumber")
        customer_digits = _phone_digit_variants(customer_phone)
        if customer_digits and candidate_digits.intersection(customer_digits):
            return {"success": True, "customer": customer, "new_customer": False}

    return {"success": False, "error": "Customer not found.", "new_customer": True}


async def resolve_business_context(
    business_number: str,
    caller_number: Optional[str] = None,
) -> Dict[str, Any]:
    logger.debug(
        "connection_store.resolve_business_context called (business_number=%s caller_number=%s)",
        business_number,
        caller_number,
    )
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
    timezone_name = location.get("timezone") if location else None

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

    bookings_result = await _fetch_square_bookings_for_month(
        access_token,
        location_id,
        timezone_name,
    )
    if not bookings_result.get("success"):
        logger.warning(
            "Square bookings lookup failed for locationId=%s: %s",
            location_id,
            bookings_result.get("error"),
        )

    prefetched_customer = None
    if caller_number:
        customer_result = await fetch_square_customer_by_phone(access_token, caller_number)
        prefetched_customer = {
            "success": customer_result.get("success", False),
            "customer": customer_result.get("customer"),
            "newCustomer": customer_result.get("new_customer", False),
            "error": customer_result.get("error"),
        }
        if not customer_result.get("success"):
            logger.info(
                "No Square customer found for caller %s (new=%s)",
                caller_number,
                customer_result.get("new_customer"),
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
        "prefetchedAppointments": bookings_result,
        "prefetchedCustomer": prefetched_customer,
    }
