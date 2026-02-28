"""
Service for resolving business context in API and websocket flows.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from vakdeepgram.connection_store import resolve_business_context
from repositories import (
    get_connection_context_by_id,
    set_connection_context_by_id,
)

logger = logging.getLogger(__name__)


async def resolve_context_for_request(
    business_number: str,
    *,
    caller_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve business context for stateless request flows (/chat, /twilio-chat)."""
    try:
        context = await resolve_business_context(business_number, caller_number=caller_number)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to resolve business context: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}
    if caller_number and isinstance(context, dict):
        context["caller"] = caller_number
    return context


async def resolve_and_store_connection_context(
    connection_id: str,
    business_number: str,
    *,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve business context and merge it into connection state."""
    caller_number = (extra_context or {}).get("caller")
    context = await resolve_context_for_request(business_number, caller_number=caller_number)
    existing_context = get_connection_context_by_id(connection_id)
    merged_context = {**existing_context, **context}
    if extra_context:
        merged_context.update(extra_context)
    set_connection_context_by_id(connection_id, merged_context)
    return merged_context
