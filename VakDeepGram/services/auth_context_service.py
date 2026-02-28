"""
Service for provider auth/access context resolution.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from providers.clients import ensure_provider_access_context
from repositories import get_connection_context_by_id


async def resolve_auth_for_business_context(
    business_context: Optional[Dict[str, Any]],
    *,
    connection_id: Optional[str] = None,
    require_location: bool = False,
) -> Dict[str, Any]:
    auth = await ensure_provider_access_context(
        business_context=business_context or {},
        connection_id=connection_id,
        require_location=require_location,
    )
    if not auth.get("success"):
        return auth
    return {
        "success": True,
        "provider": auth.get("provider"),
        "access_token": auth.get("access_token"),
        "refresh_token": auth.get("refresh_token"),
        "location_id": auth.get("location_id"),
        "business_number": auth.get("business_number"),
    }


async def resolve_auth_for_connection(
    connection_id: Optional[str],
    *,
    require_location: bool = False,
) -> Dict[str, Any]:
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}
    context = get_connection_context_by_id(connection_id)
    auth = await resolve_auth_for_business_context(
        context,
        connection_id=connection_id,
        require_location=require_location,
    )
    if not auth.get("success"):
        return auth
    return {
        "success": True,
        "context": get_connection_context_by_id(connection_id),
        "provider": auth.get("provider"),
        "access_token": auth.get("access_token"),
        "refresh_token": auth.get("refresh_token"),
        "location_id": auth.get("location_id"),
        "business_number": auth.get("business_number"),
    }

