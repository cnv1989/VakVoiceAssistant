"""
Centralized Square API response parsing and utilities.
"""
import logging
from typing import Any, Dict, Optional

try:
    from square.environment import SquareEnvironment
except Exception:
    SquareEnvironment = None

import config

logger = logging.getLogger(__name__)


def get_square_environment():
    """Get the Square environment based on config."""
    env = config.settings.square_environment
    if SquareEnvironment:
        if env.value == "sandbox":
            return SquareEnvironment.SANDBOX
        return SquareEnvironment.PRODUCTION
    return env.value


def parse_square_response(response: Any) -> Dict[str, Any]:
    """Parse a Square API response into a standardized format.

    Args:
        response: Square API response object

    Returns:
        Dict with 'success' bool, and either 'payload' or 'error'
    """
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


def extract_square_cursor(response: Any) -> Optional[str]:
    """Extract pagination cursor from Square API response.

    Args:
        response: Square API response object

    Returns:
        Cursor string if present, None otherwise
    """
    for attr in ("_response", "response", "__response"):
        page = getattr(response, attr, None)
        if page:
            return getattr(page, "cursor", None)
    return None
