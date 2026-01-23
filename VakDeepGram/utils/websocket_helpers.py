"""
Helper functions for WebSocket endpoints
"""
import logging
import uuid
import asyncio
from typing import Optional
from connection_store import (
    get_connection_context,
    resolve_business_context,
    set_connection_context,
    normalize_phone_number,
)
from business_logic import prefetch_customer_by_phone

logger = logging.getLogger(__name__)


async def resolve_and_set_context(
    connection_id: str,
    business_number: str,
    extra_context: Optional[dict] = None,
) -> None:
    """Resolve business context and set it in connection store"""
    logger.debug(
        "resolve_and_set_context called (connection_id=%s business_number=%s)",
        connection_id,
        business_number,
    )
    try:
        caller_number = extra_context.get("caller") if extra_context else None
        context = await resolve_business_context(business_number, caller_number=caller_number)
    except Exception as exc:
        logger.error(
            "Failed to resolve business context for %s: %s",
            connection_id,
            exc,
            exc_info=True,
        )
        context = {"success": False, "error": str(exc)}

    existing_context = get_connection_context(connection_id)
    merged_context = {**existing_context, **context}
    if extra_context:
        merged_context.update(extra_context)

    set_connection_context(connection_id, merged_context)
    if not merged_context.get("success"):
        logger.warning("Failed to resolve business context: %s", merged_context.get("error"))


async def prefetch_and_set_customer(connection_id: str, caller_number: Optional[str]) -> None:
    """Prefetch customer information and store in connection context"""
    logger.debug(
        "prefetch_and_set_customer called (connection_id=%s caller_number=%s)",
        connection_id,
        caller_number,
    )
    if not caller_number:
        return
    existing_context = get_connection_context(connection_id)
    if existing_context.get("prefetchedCustomer"):
        return
    normalized = normalize_phone_number(caller_number)
    try:
        result = await prefetch_customer_by_phone(
            normalized or caller_number,
            connection_id=connection_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to prefetch customer for %s: %s",
            connection_id,
            exc,
            exc_info=True,
        )
        return
    if not result.get("success") and not result.get("newCustomer"):
        return
    existing_context["prefetchedCustomer"] = result
    set_connection_context(connection_id, existing_context)
