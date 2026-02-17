"""
Shared helpers used by both Square and Setmore tool implementations.

Thin wrappers around utils.booking_helpers and common context access patterns.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from strands.types.tools import ToolContext

from utils import booking_helpers
from utils.case import to_snake_case
from utils.phone import normalize_phone_number

logger = logging.getLogger(__name__)


# ── Context access ────────────────────────────────────────────────────────────

def get_business_context(tool_context: Optional[ToolContext]) -> dict:
    """Extract business context from tool_context.agent.state or invocation_state."""
    if not tool_context:
        return {}
    def _looks_like_business_context(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        return any(
            key in value
            for key in (
                "provider",
                "services",
                "staff",
                "businessNumber",
                "business_number",
                "bookingProvider",
            )
        )
    # Prefer agent.state.get (Strands State API)
    agent = getattr(tool_context, "agent", None)
    if agent is not None:
        state = getattr(agent, "state", None)
        if state is not None and hasattr(state, "get"):
            ctx = state.get("business_context")
            full_state = state.get()
            if isinstance(ctx, dict):
                flat = dict(full_state) if isinstance(full_state, dict) else {}
                flat.pop("business_context", None)
                return to_snake_case({**ctx, **flat})
            if isinstance(full_state, dict) and _looks_like_business_context(full_state):
                return to_snake_case(full_state)
    # Fallback: invocation_state (some Strands versions may pass state here)
    inv = getattr(tool_context, "invocation_state", None) or {}
    ctx = inv.get("business_context") if hasattr(inv, "get") else None
    if isinstance(ctx, dict):
        return to_snake_case(ctx)
    if _looks_like_business_context(inv):
        return to_snake_case(inv)
    # Last resort: some tool_context variants expose state directly
    direct_state = getattr(tool_context, "state", None) or getattr(tool_context, "_state", None) or {}
    if isinstance(direct_state, dict):
        ctx = direct_state.get("business_context")
        if isinstance(ctx, dict):
            return to_snake_case(ctx)
        if _looks_like_business_context(direct_state):
            return to_snake_case(direct_state)
    return {}


def update_business_context(tool_context: ToolContext, updates: dict) -> dict:
    """Update business_context and flatten keys into agent state using state.set()."""
    if not tool_context or not getattr(tool_context, "agent", None):
        return {}
    agent_state = tool_context.agent.state
    if agent_state is None or not hasattr(agent_state, "get") or not hasattr(agent_state, "set"):
        return {}
    existing = agent_state.get("business_context") or {}
    if not isinstance(existing, dict):
        existing = {}
    if not existing:
        full_state = agent_state.get()
        if isinstance(full_state, dict):
            existing = dict(full_state)
            existing.pop("business_context", None)
    merged = dict(existing)
    merged.update(updates)
    merged = to_snake_case(merged)
    agent_state.set("business_context", merged)
    for key, value in merged.items():
        if key == "business_context":
            continue
        agent_state.set(key, value)
    return get_business_context(tool_context)


def provider_from_context(business_context: dict) -> str:
    """Return 'square' or 'setmore' from context."""
    return (business_context.get("provider") or "square").lower()


def get_access_token(business_context: dict) -> Optional[str]:
    """Extract access token from context."""
    return business_context.get("accessToken") or business_context.get("access_token")


# ── Date / time helpers (delegate to booking_helpers) ─────────────────────────

parse_datetime = booking_helpers.parse_datetime
isoformat_utc = booking_helpers.isoformat_utc
start_of_day = booking_helpers.start_of_day
end_of_day = booking_helpers.end_of_day
ensure_minimum_range = booking_helpers.ensure_minimum_range
resolve_location_timezone = booking_helpers.resolve_location_timezone
resolve_date_range = booking_helpers.resolve_date_range
relative_range = booking_helpers.relative_range
resolve_weekday_range = booking_helpers.resolve_weekday_range

# ── Service / staff helpers ───────────────────────────────────────────────────

suggest_services = booking_helpers.suggest_services
select_service_variation_id = booking_helpers.select_service_variation_id
match_service_variation = booking_helpers.match_service_variation
resolve_staff_ids = booking_helpers.resolve_staff_ids
staff_display_name = booking_helpers.staff_display_name
resolve_available_staff = booking_helpers.resolve_available_staff

# ── Availability helpers ──────────────────────────────────────────────────────

availability_start_at = booking_helpers.availability_start_at
availability_duration_minutes = booking_helpers.availability_duration_minutes
availability_team_member_ids = booking_helpers.availability_team_member_ids
availability_start_dt = booking_helpers.availability_start_dt
availability_supports_start = booking_helpers.availability_supports_start
availability_window_minutes = booking_helpers.availability_window_minutes
format_availability_response = booking_helpers.format_availability_response

# ── Booking helpers ───────────────────────────────────────────────────────────

booking_segments = booking_helpers.booking_segments
booking_version = booking_helpers.booking_version
extract_booking_segment_details = booking_helpers.extract_booking_segment_details


def as_dict(value: Any) -> Any:
    """Convert SDK model objects to plain dicts."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value
