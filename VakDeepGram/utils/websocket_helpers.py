"""
Helper functions for WebSocket endpoints
"""
import logging
from typing import Optional
from vakdeepgram.connection_store import (
    get_connection_context,
    resolve_business_context,
    set_connection_context,
)

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
