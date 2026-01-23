"""
Tests for PII redaction in logging.
"""
import pytest
import logging
from utils.logging import PIIRedactingFormatter


class TestPIIRedaction:
    """Tests for PII redacting log formatter."""

    @pytest.fixture
    def formatter(self):
        return PIIRedactingFormatter(
            fmt="%(message)s",
            redact_phone=True,
            redact_email=True,
            redact_tokens=True,
        )

    def test_redacts_phone_number(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Customer phone: 555-123-4567",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "555-123-4567" not in result
        assert "[PHONE:***4567]" in result

    def test_redacts_formatted_phone(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Phone is (555) 123-4567",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "555" not in result or "[PHONE:" in result

    def test_redacts_email(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Email: john.doe@example.com",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "john.doe" not in result
        assert "[EMAIL:***@example.com]" in result

    def test_redacts_square_tokens(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token: sq0atp-abcdefghijklmnopqrstuvwxyz1234567890",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "abcdefghijklmnopqrstuvwxyz" not in result
        assert "[TOKEN:***]" in result

    def test_preserves_non_pii(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Connection established for user session",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert result == "Connection established for user session"

    def test_multiple_pii_in_message(self, formatter):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Contact: 555-123-4567, email: test@example.com",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "555-123-4567" not in result
        assert "test@" not in result
        assert "[PHONE:" in result
        assert "[EMAIL:" in result


class TestPIIRedactionDisabled:
    """Tests for PII redaction when disabled."""

    def test_no_phone_redaction(self):
        formatter = PIIRedactingFormatter(
            fmt="%(message)s",
            redact_phone=False,
            redact_email=True,
            redact_tokens=True,
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Phone: 555-123-4567",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "555-123-4567" in result

    def test_no_email_redaction(self):
        formatter = PIIRedactingFormatter(
            fmt="%(message)s",
            redact_phone=True,
            redact_email=False,
            redact_tokens=True,
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Email: test@example.com",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "test@example.com" in result
