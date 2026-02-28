"""
Tests for connection store functionality.
"""
import pytest
import time
from unittest.mock import patch


class TestConnectionStore:
    """Tests for connection store functions."""

    def test_set_and_get_context(self):
        from vakdeepgram.connection_store import (
            set_connection_context,
            get_connection_context,
            clear_connection_context,
        )

        conn_id = "test-conn-1"
        context = {"foo": "bar", "baz": 123}

        set_connection_context(conn_id, context)
        result = get_connection_context(conn_id)

        assert result == context
        assert result["foo"] == "bar"
        assert result["baz"] == 123

        clear_connection_context(conn_id)
        assert get_connection_context(conn_id) == {}

    def test_update_context(self):
        from vakdeepgram.connection_store import (
            set_connection_context,
            update_connection_context,
            get_connection_context,
            clear_connection_context,
        )

        conn_id = "test-conn-2"
        initial = {"foo": "bar"}
        set_connection_context(conn_id, initial)

        update_connection_context(conn_id, {"baz": 123})
        result = get_connection_context(conn_id)

        assert result["foo"] == "bar"
        assert result["baz"] == 123

        clear_connection_context(conn_id)

    def test_clear_nonexistent_context(self):
        from vakdeepgram.connection_store import clear_connection_context, get_connection_context

        # Should not raise
        clear_connection_context("nonexistent-conn")
        assert get_connection_context("nonexistent-conn") == {}


class TestConnectionTimestamps:
    """Tests for connection timestamp tracking."""

    def test_timestamp_set_on_context(self):
        from vakdeepgram.connection_store import (
            set_connection_context,
            clear_connection_context,
            _connection_timestamps,
        )

        conn_id = "test-conn-ts-1"
        before = time.time()
        set_connection_context(conn_id, {"test": True})
        after = time.time()

        assert conn_id in _connection_timestamps
        assert before <= _connection_timestamps[conn_id] <= after

        clear_connection_context(conn_id)
        assert conn_id not in _connection_timestamps

    def test_timestamp_cleared_on_clear(self):
        from vakdeepgram.connection_store import (
            set_connection_context,
            clear_connection_context,
            _connection_timestamps,
        )

        conn_id = "test-conn-ts-2"
        set_connection_context(conn_id, {"test": True})
        assert conn_id in _connection_timestamps

        clear_connection_context(conn_id)
        assert conn_id not in _connection_timestamps
