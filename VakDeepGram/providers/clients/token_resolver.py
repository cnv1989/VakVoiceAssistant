from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from vakdeepgram.connection_store import (
    get_connection_context,
    get_setmore_access_token_from_dynamodb,
    resolve_business_context,
    update_connection_context,
)
from utils import setmore_api

logger = logging.getLogger(__name__)


def _provider_from_context(context: Dict[str, Any]) -> str:
    return (context.get("provider") or "square").lower()


def _get_business_number(context: Dict[str, Any]) -> Optional[str]:
    return (
        context.get("business_number")
        or context.get("businessNumber")
        or context.get("called")
        or (context.get("location") or {}).get("phone_number")
    )


def _read_access_context(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": _provider_from_context(context),
        "access_token": context.get("accessToken") or context.get("access_token"),
        "refresh_token": context.get("refreshToken") or context.get("refresh_token"),
        "location_id": context.get("locationId") or context.get("location_id"),
        "business_number": _get_business_number(context),
    }


def _merge_context_updates(context: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(context or {})
    merged.update({k: v for k, v in updates.items() if v is not None})
    return merged


async def ensure_provider_access_context(
    *,
    business_context: Optional[Dict[str, Any]] = None,
    connection_id: Optional[str] = None,
    require_location: bool = False,
) -> Dict[str, Any]:
    """Ensure provider auth context is present, refreshing from DynamoDB where needed."""
    base_context: Dict[str, Any] = {}
    if connection_id:
        base_context = get_connection_context(connection_id) or {}
    if business_context:
        base_context = _merge_context_updates(base_context, business_context)

    ctx = _read_access_context(base_context)
    provider = ctx["provider"]

    if provider == "setmore":
        business_number = ctx.get("business_number")
        if business_number:
            token_result = await get_setmore_access_token_from_dynamodb(str(business_number))
            if token_result.get("success") and token_result.get("access_token"):
                ctx["access_token"] = token_result["access_token"]
                update = {"accessToken": token_result["access_token"], "access_token": token_result["access_token"]}
                if connection_id:
                    update_connection_context(connection_id, update)
            else:
                logger.warning("Setmore token fetch from DynamoDB failed: %s", token_result.get("error"))

        if not ctx.get("access_token") and ctx.get("refresh_token"):
            token_result = await setmore_api.get_access_token(ctx["refresh_token"])
            if token_result.get("success") and token_result.get("access_token"):
                ctx["access_token"] = token_result["access_token"]
                update = {"accessToken": token_result["access_token"], "access_token": token_result["access_token"]}
                if connection_id:
                    update_connection_context(connection_id, update)

        if not ctx.get("access_token"):
            return {"success": False, "error": "Missing Setmore access token."}
        return {
            "success": True,
            "provider": provider,
            "access_token": ctx["access_token"],
            "refresh_token": ctx.get("refresh_token"),
            "location_id": ctx.get("location_id"),
            "business_number": ctx.get("business_number"),
        }

    if not ctx.get("access_token") or (require_location and not ctx.get("location_id")):
        business_number = ctx.get("business_number")
        if business_number:
            resolved = await resolve_business_context(str(business_number))
            if resolved.get("success"):
                ctx["access_token"] = resolved.get("accessToken") or resolved.get("access_token")
                ctx["location_id"] = resolved.get("locationId") or resolved.get("location_id")
                if connection_id:
                    update_connection_context(connection_id, resolved)
            else:
                return {"success": False, "error": resolved.get("error") or "Failed to resolve Square context."}

    if not ctx.get("access_token"):
        return {"success": False, "error": "Missing Square access token."}
    if require_location and not ctx.get("location_id"):
        return {"success": False, "error": "Missing Square location ID."}
    return {
        "success": True,
        "provider": provider,
        "access_token": ctx["access_token"],
        "refresh_token": ctx.get("refresh_token"),
        "location_id": ctx.get("location_id"),
        "business_number": ctx.get("business_number"),
    }

