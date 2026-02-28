"""
Repository wrapper around in-memory connection context storage.
"""

from __future__ import annotations

from typing import Any, Dict

from vakdeepgram.connection_store import (
    get_connection_context,
    set_connection_context,
    update_connection_context,
    clear_connection_context,
)


def get_connection_context_by_id(connection_id: str) -> Dict[str, Any]:
    return get_connection_context(connection_id)


def set_connection_context_by_id(connection_id: str, context: Dict[str, Any]) -> None:
    set_connection_context(connection_id, context)


def update_connection_context_by_id(connection_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    return update_connection_context(connection_id, updates)


def clear_connection_context_by_id(connection_id: str) -> None:
    clear_connection_context(connection_id)
