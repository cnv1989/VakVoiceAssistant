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
from utils.phone import normalize_phone_number

logger = logging.getLogger(__name__)


# ── Context access ────────────────────────────────────────────────────────────

def get_business_context(tool_context: Optional[ToolContext]) -> dict:
    """Extract business context from tool_context.agent.state or invocation_state."""
    if not tool_context:
        return {}
    # Prefer agent.state (set when creating the Agent in main.py)
    agent = getattr(tool_context, "agent", None)
    if agent is not None:
        state = getattr(agent, "state", None) or {}
        ctx = state.get("business_context")
        if ctx is not None:
            return ctx
    # Fallback: invocation_state (some Strands versions may pass state here)
    inv = getattr(tool_context, "invocation_state", None) or {}
    return inv.get("business_context") or {}


def update_business_context(tool_context: ToolContext, updates: dict) -> dict:
    """Persist chat selections in the agent state."""
    if not tool_context or not getattr(tool_context, "agent", None):
        return {}
    state = tool_context.agent.state or {}
    business_context = state.get("business_context") or {}
    business_context.update(updates)
    state["business_context"] = business_context
    tool_context.agent.state = state
    return business_context


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
