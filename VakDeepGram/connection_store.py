"""
Helpers for resolving business context from DynamoDB for Square/Setmore integrations.
"""
import asyncio
import copy
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import aioboto3
from square import AsyncSquare
from square.core.api_error import ApiError as SquareApiError

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

import config
from utils import setmore_api
from utils.square_helpers import (
    get_square_environment as _square_environment,
    parse_square_response as _parse_square_response,
    extract_square_cursor as _extract_square_cursor,
)
from utils.phone import (
    normalize_phone_number,
    phone_digit_variants as _phone_digit_variants,
    candidate_numbers as _candidate_numbers,
)
from utils.context_optimizer import (
    optimize_location,
    optimize_services,
    optimize_staff,
    optimize_customer,
)

logger = logging.getLogger(__name__)

# Connection context storage with timestamps for TTL
_connection_contexts: Dict[str, Dict[str, Any]] = {}
_connection_timestamps: Dict[str, float] = {}
_business_context_cache: Dict[tuple, Dict[str, Any]] = {}
_business_context_timestamps: Dict[tuple, float] = {}
_SERVICE_PRODUCT_TYPES = ["APPOINTMENTS_SERVICE", "LEGACY_SQUARE_ONLINE_SERVICE"]
_cleanup_task_started = False


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _get_cached_business_context(cache_keys: list[tuple]) -> Optional[Dict[str, Any]]:
    ttl = config.settings.business_context_ttl_seconds
    now = time.time()
    for key in cache_keys:
        timestamp = _business_context_timestamps.get(key)
        if not timestamp:
            continue
        if now - timestamp > ttl:
            _business_context_cache.pop(key, None)
            _business_context_timestamps.pop(key, None)
            continue
        cached = _business_context_cache.get(key)
        if cached:
            return copy.deepcopy(cached)
    return None


async def _cleanup_expired_connections() -> None:
    """Background task to clean up expired connection contexts."""
    global _cleanup_task_started
    _cleanup_task_started = True
    logger.debug("Starting connection cleanup background task")

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            ttl = config.settings.connection_ttl_seconds
            now = time.time()
            expired = []

            for conn_id, timestamp in list(_connection_timestamps.items()):
                if now - timestamp > ttl:
                    expired.append(conn_id)

            for conn_id in expired:
                _connection_contexts.pop(conn_id, None)
                _connection_timestamps.pop(conn_id, None)
                logger.debug("Cleaned up expired connection: %s", conn_id)

            if expired:
                logger.info("Cleaned up %d expired connections", len(expired))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in connection cleanup task: %s", e)


def start_cleanup_task() -> None:
    """Start the connection cleanup background task if not already running."""
    global _cleanup_task_started
    if not _cleanup_task_started:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_cleanup_expired_connections())
        except RuntimeError:
            # No running loop yet, will be started later
            pass


def set_connection_context(connection_id: str, context: Dict[str, Any]) -> None:
    logger.debug("connection_store.set_connection_context called (connection_id=%s)", connection_id)
    _connection_contexts[connection_id] = context
    _connection_timestamps[connection_id] = time.time()
    start_cleanup_task()


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
    logger.debug("connection_store.clear_connection_context called (connection_id=%s)", connection_id)
    _connection_contexts.pop(connection_id, None)
    _connection_timestamps.pop(connection_id, None)


def get_localized_datetime_for_connection(connection_id: str) -> str:
    """Return a localized datetime string based on the connection's location ID."""
    logger.info("connection_store.get_localized_datetime_for_connection called (connection_id=%s)", connection_id)
    context = get_connection_context(connection_id)
    location = context.get("location") or {}
    timezone_name = location.get("timezone") or context.get("timezone")
    now = datetime.now(ZoneInfo(timezone_name)) if timezone_name and ZoneInfo else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S (%A, %B %d, %Y)")


def get_localized_datetime_from_context(business_context: dict) -> str:
    """Return a localized datetime string based on the business context's timezone."""
    location = business_context.get("location") or {}
    timezone_name = location.get("timezone") or business_context.get("timezone")
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


async def _prefetch_availability_for_services(
    access_token: str,
    location_id: str,
    services: list,
    timezone_name: Optional[str],
    days: int = 30,
) -> Dict[str, Any]:
    """
    Prefetch availability for all services for the next N days.

    Returns availability indexed by service_variation_id and date for efficient lookup.
    This allows answering availability queries without making on-demand API calls.
    """
    logger.info(
        "Prefetching availability for %d days (location=%s services=%d)",
        days,
        location_id,
        len(services or []),
    )

    # Calculate date range
    tzinfo = ZoneInfo(timezone_name) if timezone_name and ZoneInfo else None
    now = datetime.now(tzinfo) if tzinfo else datetime.now(timezone.utc)
    start_at = _isoformat_utc(now)
    end_at = _isoformat_utc(now + timedelta(days=days))

    # Collect all service variation IDs with their duration (None if missing/invalid)
    # Format: list of (var_id, duration_minutes or None)
    DEFAULT_DURATION_MINUTES = 30
    service_variations = []
    missing_duration_count = 0
    for item in services or []:
        # Handle both full Square format and optimized format
        if "item_data" in item:
            # Full Square format - duration is in milliseconds
            item_data = item.get("item_data") or {}
            for variation in item_data.get("variations") or []:
                var_id = variation.get("id")
                if not var_id:
                    continue
                var_data = variation.get("item_variation_data") or {}
                duration_ms = var_data.get("service_duration")
                # Convert to minutes, use None if missing/invalid (< 1 minute)
                if duration_ms and duration_ms >= 60000:
                    duration_minutes = int(duration_ms / 60000)
                else:
                    duration_minutes = None
                    missing_duration_count += 1
                service_variations.append((var_id, duration_minutes))
        elif "variations" in item:
            # Optimized format - duration is in minutes
            for variation in item.get("variations") or []:
                var_id = variation.get("id")
                if not var_id:
                    continue
                duration_minutes = variation.get("duration_minutes")
                # Use None if missing/invalid (< 1 minute)
                if not duration_minutes or duration_minutes < 1:
                    duration_minutes = None
                    missing_duration_count += 1
                service_variations.append((var_id, duration_minutes))

    if missing_duration_count > 0:
        logger.info(
            "Using default %d min duration for %d service variations without valid duration",
            DEFAULT_DURATION_MINUTES,
            missing_duration_count,
        )

    if not service_variations:
        logger.warning("No service variations found for availability prefetch")
        return {"success": False, "error": "No service variations found."}

    client = AsyncSquare(token=access_token, environment=_square_environment())

    # Fetch availability for each service variation
    by_service: Dict[str, Dict[str, list]] = {}

    for service_variation_id, duration_minutes in service_variations:
        try:
            # Build segment filter - include explicit duration if service doesn't have one
            segment_filter = {"service_variation_id": service_variation_id}
            if duration_minutes is None:
                segment_filter["duration_minutes"] = DEFAULT_DURATION_MINUTES

            filter_payload = {
                "start_at_range": {"start_at": start_at, "end_at": end_at},
                "location_id": location_id,
                "segment_filters": [segment_filter],
            }

            response = await client.bookings.search_availability(
                query={"filter": filter_payload}
            )
            parsed = _parse_square_response(response)

            if not parsed.get("success"):
                logger.warning(
                    "Availability prefetch failed for service %s: %s",
                    service_variation_id,
                    parsed.get("error"),
                )
                continue

            availabilities = parsed.get("payload", {}).get("availabilities") or []

            # Process and index availability by date
            service_slots: Dict[str, list] = {}
            for avail in availabilities:
                # Handle both dict and object formats
                if hasattr(avail, "model_dump"):
                    avail = avail.model_dump()

                start_at_str = avail.get("start_at") or avail.get("startAt")
                if not start_at_str:
                    continue

                # Parse start time
                normalized = start_at_str.replace("Z", "+00:00")
                try:
                    start_dt = datetime.fromisoformat(normalized)
                    if tzinfo:
                        start_dt = start_dt.astimezone(tzinfo)
                except ValueError:
                    continue

                date_key = start_dt.date().isoformat()
                time_str = start_dt.strftime("%H:%M")

                # Extract segments
                segments = avail.get("appointment_segments") or avail.get("appointmentSegments") or []
                duration_minutes = None
                team_member_ids = []
                for seg in segments:
                    if hasattr(seg, "model_dump"):
                        seg = seg.model_dump()
                    if isinstance(seg, dict):
                        dm = seg.get("duration_minutes") or seg.get("durationMinutes")
                        tm_id = seg.get("team_member_id") or seg.get("teamMemberId")
                    else:
                        dm = getattr(seg, "duration_minutes", None) or getattr(seg, "durationMinutes", None)
                        tm_id = getattr(seg, "team_member_id", None) or getattr(seg, "teamMemberId", None)
                    if dm and duration_minutes is None:
                        duration_minutes = dm
                    if tm_id:
                        team_member_ids.append(tm_id)

                slot = {
                    "start_at": start_at_str,
                    "time": time_str,
                    "duration_minutes": duration_minutes,
                    "team_member_ids": team_member_ids,
                }

                # Index by date
                if date_key not in service_slots:
                    service_slots[date_key] = []
                service_slots[date_key].append(slot)

            by_service[service_variation_id] = service_slots

        except SquareApiError as exc:
            # Square API errors (e.g., invalid duration) - log as warning and skip
            logger.warning(
                "Square API error prefetching availability for service %s: %s",
                service_variation_id,
                exc,
            )
        except Exception as exc:
            logger.error(
                "Error prefetching availability for service %s: %s",
                service_variation_id,
                exc,
                exc_info=True,
            )

    # Count total dates with availability
    all_dates = set()
    for service_data in by_service.values():
        all_dates.update(service_data.keys())

    logger.info(
        "Prefetched availability: %d services, %d dates",
        len(by_service),
        len(all_dates),
    )

    return {
        "success": True,
        "start_date": now.date().isoformat(),
        "end_date": (now + timedelta(days=days)).date().isoformat(),
        "by_service": by_service,
    }


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


async def _fetch_setmore_account_record(
    account_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    logger.debug(
        "connection_store._fetch_setmore_account_record called (account_id=%s user_id=%s)",
        account_id,
        user_id,
    )
    if not account_id and not user_id:
        return None
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=config.settings.aws_region) as dynamodb:
        table = dynamodb.Table(config.settings.setmore_account_table)
        if asyncio.iscoroutine(table):
            table = await table
        key_candidates = []
        # Amplify Gen 2 schema uses "id" as partition key for SetmoreAccount
        if account_id:
            key_candidates.append({"id": account_id})
        if account_id and user_id:
            key_candidates.append({"accountId": account_id, "userId": user_id})
            key_candidates.append({"setmoreAccountId": account_id, "setmoreUserId": user_id})
        if account_id:
            key_candidates.append({"accountId": account_id})
            key_candidates.append({"setmoreAccountId": account_id})
        if user_id:
            key_candidates.append({"id": user_id})
            key_candidates.append({"userId": user_id})
            key_candidates.append({"setmoreUserId": user_id})
        for key in key_candidates:
            try:
                response = await table.get_item(Key=key)
                item = response.get("Item")
                if item:
                    return item
            except Exception as exc:
                # Key structure may not match table schema — try next candidate
                logger.debug(
                    "Setmore account lookup failed for key %s: %s",
                    list(key.keys()),
                    exc,
                )
                continue
        return None


def _build_service_category_map(
    categories: Optional[list[Dict[str, Any]]],
) -> Dict[str, Dict[str, str]]:
    """Build a mapping from service key to {category_id, category_name}.

    Setmore returns a default "All Services" umbrella category that contains
    every service.  When real categories exist we exclude the umbrella so
    services are grouped by their meaningful category.
    """
    mapping: Dict[str, Dict[str, str]] = {}
    if not categories:
        return mapping
    specific = [
        cat for cat in categories
        if (cat.get("category_name") or "").lower() != "all services"
    ]
    effective = specific if specific else categories
    for cat in effective:
        cat_key = cat.get("key") or ""
        cat_name = cat.get("category_name") or "Uncategorized"
        for service_key in cat.get("service_id_list") or []:
            mapping[service_key] = {"category_id": cat_key, "category_name": cat_name}
    return mapping


def _normalize_setmore_services(
    services: Optional[list[Dict[str, Any]]],
    categories: Optional[list[Dict[str, Any]]] = None,
) -> list[Dict[str, Any]]:
    if not services:
        return []
    cat_map = _build_service_category_map(categories)
    normalized = []
    for service in services:
        service_key = service.get("key")
        name = service.get("service_name") or service.get("name")
        duration = service.get("duration")
        price = service.get("cost")
        currency = service.get("currency")
        cat_info = cat_map.get(service_key) or {}
        normalized.append(
            {
                "id": service_key,
                "name": name,
                "description": service.get("description"),
                "duration_minutes": duration,
                "category_id": cat_info.get("category_id"),
                "category_name": cat_info.get("category_name"),
                "staff_keys": service.get("staff_keys") or [],
                "variations": [
                    {
                        "id": service_key,
                        "name": name,
                        "duration_minutes": duration,
                        "price": {"amount": price, "currency": currency} if price is not None else None,
                    }
                ],
                "raw": service,
            }
        )
    return normalized


def _normalize_setmore_staff(staffs: Optional[list[Dict[str, Any]]]) -> list[Dict[str, Any]]:
    if not staffs:
        return []
    normalized = []
    for staff in staffs:
        first = staff.get("first_name") or ""
        last = staff.get("last_name") or ""
        display_name = " ".join(part for part in [first, last] if part).strip() or None
        normalized.append(
            {
                "id": staff.get("key"),
                "display_name": display_name,
                "status": "ACTIVE",
                "raw": staff,
            }
        )
    return normalized


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




async def _fetch_square_customers(access_token: str) -> Dict[str, Any]:
    logger.info("connection_store._fetch_square_customers called")
    logger.info("Fetching Square customers")
    client = AsyncSquare(token=access_token, environment=_square_environment())
    customers: list[Dict[str, Any]] = []
    cursor = None
    while True:
        response = await client.customers.list(cursor=cursor, limit=100)
        if hasattr(response, "__aiter__"):
            async for customer in response:
                customers.append(_as_dict(customer))
            cursor = _extract_square_cursor(response)
            if not cursor:
                break
            continue
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
        customer_dict = _as_dict(customer)
        customer_phone = customer_dict.get("phone_number") or customer_dict.get("phoneNumber")
        customer_digits = _phone_digit_variants(customer_phone)
        if customer_digits and candidate_digits.intersection(customer_digits):
            return {"success": True, "customer": customer_dict, "new_customer": False}

    return {"success": False, "error": "Customer not found.", "new_customer": True}


async def resolve_business_context(
    business_number: str,
    caller_number: Optional[str] = None,
    optimize: Optional[bool] = None,
    prefetch_availability_days: Optional[int] = None,
) -> Dict[str, Any]:
    # Use config defaults if not specified
    if optimize is None:
        optimize = config.settings.optimize_business_context
    if prefetch_availability_days is None:
        prefetch_availability_days = config.settings.prefetch_availability_days

    logger.info(
        "connection_store.resolve_business_context called (business_number=%s caller_number=%s optimize=%s prefetch_days=%d)",
        business_number,
        caller_number,
        optimize,
        prefetch_availability_days,
    )
    candidates = _candidate_numbers(business_number)
    if not candidates:
        logger.warning("Business number normalization failed: %s", business_number)
        return {"success": False, "error": "Invalid business number."}

    cache_keys = [(candidate, bool(optimize), int(prefetch_availability_days)) for candidate in candidates]
    cached = _get_cached_business_context(cache_keys)
    if cached:
        logger.info("Returning cached business context for %s", business_number)
        return cached

    logger.info("Resolving business context for %s (candidates=%s)", business_number, candidates)
    record = None
    matched_number = None
    for candidate in candidates:
        record = await _fetch_business_number_record(candidate)
        if record:
            matched_number = candidate
            break
        logger.warning("No BusinessNumber record found for %s", candidate)

    if not record:
        logger.warning("No BusinessNumber record found for %s", candidates)
        return {"success": False, "error": "Business number not found."}

    provider = (record.get("provider") or record.get("bookingProvider") or "square").lower()

    if provider == "setmore":
        account_id = (
            record.get("setmoreAccountId")
            or record.get("setmore_account_id")
            or record.get("accountId")
        )
        account_user_id = (
            record.get("setmoreUserId")
            or record.get("setmore_user_id")
            or record.get("userId")
            or record.get("ownerId")
        )
        refresh_token = (
            record.get("setmoreRefreshToken")
            or record.get("setmore_refresh_token")
            or record.get("refreshToken")
        )

        # Always fetch the SetmoreAccount record to get business details
        account = await _fetch_setmore_account_record(account_id, account_user_id)
        if not refresh_token:
            refresh_token = (account or {}).get("refreshToken") or (account or {}).get("refresh_token")
        if not refresh_token:
            logger.warning("Setmore account missing refresh token (account_id=%s user_id=%s)", account_id, account_user_id)
            return {"success": False, "error": "Setmore refresh token not found."}

        token_result = await setmore_api.get_access_token(refresh_token)
        if not token_result.get("success"):
            return {"success": False, "error": token_result.get("error")}
        access_token = token_result.get("access_token")

        # Fetch services, categories, staff, and appointments in parallel
        now = datetime.now(timezone.utc)
        appt_start = now.strftime("%d-%m-%Y")
        appt_end = (now + timedelta(days=prefetch_availability_days)).strftime("%d-%m-%Y")

        services_task = setmore_api.fetch_services(access_token, refresh_token=refresh_token)
        categories_task = setmore_api.fetch_service_categories(access_token, refresh_token=refresh_token)
        staff_task = setmore_api.fetch_staff(access_token, refresh_token=refresh_token)
        appointments_task = setmore_api.fetch_appointments(
            access_token,
            start_date=appt_start,
            end_date=appt_end,
            customer_details=True,
            refresh_token=refresh_token,
        )

        services_result, categories_result, staff_result, appointments_result = await asyncio.gather(
            services_task, categories_task, staff_task, appointments_task,
            return_exceptions=True,
        )

        # Safely unpack results (gather with return_exceptions may return Exception objects)
        if isinstance(services_result, Exception):
            logger.warning("Setmore services lookup failed: %s", services_result)
            services_result = {"success": False, "error": str(services_result)}
        if isinstance(categories_result, Exception):
            logger.warning("Setmore categories lookup failed: %s", categories_result)
            categories_result = {"success": False, "error": str(categories_result)}
        if isinstance(staff_result, Exception):
            logger.warning("Setmore staff lookup failed: %s", staff_result)
            staff_result = {"success": False, "error": str(staff_result)}
        if isinstance(appointments_result, Exception):
            logger.warning("Setmore appointments lookup failed: %s", appointments_result)
            appointments_result = {"success": False, "error": str(appointments_result)}

        services_raw = services_result.get("services") if services_result.get("success") else []
        if not services_result.get("success"):
            logger.warning("Setmore services lookup failed: %s", services_result.get("error"))

        categories_raw = categories_result.get("service_categories") if categories_result.get("success") else []
        if not categories_result.get("success"):
            logger.warning("Setmore service categories lookup failed: %s", categories_result.get("error"))

        services = _normalize_setmore_services(services_raw, categories_raw)

        staff_raw = staff_result.get("staffs") if staff_result.get("success") else []
        if not staff_result.get("success"):
            logger.warning("Setmore staff lookup failed: %s", staff_result.get("error"))
        staff = _normalize_setmore_staff(staff_raw)

        appointments_raw = appointments_result.get("appointments") if appointments_result.get("success") else []
        if not appointments_result.get("success"):
            logger.warning("Setmore appointments lookup failed: %s", appointments_result.get("error"))

        # Read business details from the SetmoreAccount record (user-provided at
        # connect time) and fall back to the BusinessNumber record fields.
        acct = account or {}
        timezone_name = (
            acct.get("timezone")
            or record.get("timezone")
            or record.get("timeZone")
        )
        booking_page_url = (
            acct.get("bookingUrl")
            or acct.get("bookingPageUrl")
            or record.get("bookingPageUrl")
            or record.get("booking_page_url")
            or record.get("setmoreBookingPage")
        )
        business_name = (
            acct.get("businessName")
            or acct.get("accountLabel")
            or record.get("businessName")
            or record.get("business_name")
        )
        business_phone = (
            acct.get("businessPhone")
            or record.get("phoneNumber")
            or record.get("phone_number")
        )
        whatsapp_number = acct.get("whatsAppNumber")
        business_address = (
            acct.get("businessAddress")
            or record.get("businessAddress")
            or record.get("business_address")
        )
        business_city = acct.get("businessCity")
        business_state = acct.get("businessState")
        business_zip = acct.get("businessZip")
        business_hours = acct.get("businessHours")
        business_email = acct.get("businessEmail") or record.get("businessEmail")
        forwarding_number = record.get("forwardingNumber") or record.get("forwarding_number")

        # Build full address from parts if not a single string
        if not business_address and (business_city or business_state):
            business_address = ", ".join(
                p for p in [business_city, business_state, business_zip] if p
            )
        elif business_address and business_city:
            business_address = f"{business_address}, {business_city}, {business_state or ''} {business_zip or ''}".strip()

        location = {
            "timezone": timezone_name,
            "business_name": business_name,
            "phone_number": business_phone,
            "whatsapp_number": whatsapp_number,
            "address": business_address,
            "email": business_email,
            "business_hours": business_hours,
        }

        result = {
            "success": True,
            "provider": "setmore",
            "businessNumber": matched_number,
            "forwardingNumber": forwarding_number,
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "accountId": account_id or acct.get("accountId") or acct.get("id"),
            "userId": account_user_id or acct.get("userId"),
            "location": location,
            "timezone": timezone_name,
            "services": services,
            "staff": staff,
            "appointments": appointments_raw,
            "customer": None,
            "setmore_services": services_raw,
            "setmore_staff": staff_raw,
            "setmore_appointments": appointments_raw,
            "bookingPageUrl": booking_page_url,
        }
        return result

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

    customer = None
    if caller_number:
        normalized_caller = normalize_phone_number(caller_number) or caller_number
        customer_result = await fetch_square_customer_by_phone(access_token, normalized_caller)
        customer = customer_result.get("customer") if customer_result.get("success") else None
        if not customer_result.get("success"):
            logger.info(
                "No Square customer found for caller %s (new=%s error=%s)",
                normalized_caller,
                customer_result.get("new_customer"),
                customer_result.get("error"),
            )

    # Apply optimizations if enabled
    if optimize:
        location = optimize_location(location)
        services = optimize_services(services)
        staff = optimize_staff(staff)
        customer = optimize_customer(customer)

    logger.info(
        "Resolved business context for %s (locationId=%s, merchantId=%s, userId=%s, optimized=%s)",
        matched_number,
        location_id,
        merchant_id,
        user_id,
        optimize,
    )

    result = {
        "success": True,
        "provider": "square",
        "businessNumber": matched_number,
        "locationId": location_id,
        "merchantId": merchant_id,
        "userId": user_id,
        "accessToken": access_token,
        "location": location,
        "services": services,
        "staff": staff,
        "customer": customer,
    }
    return result
