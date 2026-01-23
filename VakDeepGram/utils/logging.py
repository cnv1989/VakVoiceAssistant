"""
PII-redacting log formatter for VakDeepGram.
"""
import logging
import re
from typing import Optional


class PIIRedactingFormatter(logging.Formatter):
    """Log formatter that redacts PII (phone numbers, emails, tokens)."""

    # Patterns for PII detection
    PHONE_PATTERN = re.compile(
        r"(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
    )
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    )
    # Token patterns (API keys, access tokens - long alphanumeric strings)
    TOKEN_PATTERN = re.compile(
        r"(sq0[a-z]{3}-[A-Za-z0-9_-]{20,})"  # Square tokens
    )
    # Generic long secrets (32+ chars of alphanumeric)
    SECRET_PATTERN = re.compile(
        r"(?<![a-zA-Z0-9])([a-zA-Z0-9]{32,})(?![a-zA-Z0-9])"
    )

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        redact_phone: bool = True,
        redact_email: bool = True,
        redact_tokens: bool = True,
    ):
        super().__init__(fmt, datefmt)
        self.redact_phone = redact_phone
        self.redact_email = redact_email
        self.redact_tokens = redact_tokens

    def _redact_phone(self, message: str) -> str:
        """Redact phone numbers, keeping last 4 digits."""
        def replacer(match):
            phone = match.group(1)
            # Keep last 4 digits
            return f"[PHONE:***{phone[-4:]}]"
        return self.PHONE_PATTERN.sub(replacer, message)

    def _redact_email(self, message: str) -> str:
        """Redact email addresses, keeping domain."""
        def replacer(match):
            email = match.group(0)
            parts = email.split("@")
            if len(parts) == 2:
                return f"[EMAIL:***@{parts[1]}]"
            return "[EMAIL:***]"
        return self.EMAIL_PATTERN.sub(replacer, message)

    def _redact_tokens(self, message: str) -> str:
        """Redact API tokens and secrets."""
        # Redact Square-style tokens
        message = self.TOKEN_PATTERN.sub("[TOKEN:***]", message)
        # Redact other long secrets
        message = self.SECRET_PATTERN.sub("[SECRET:***]", message)
        return message

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with PII redacted."""
        # Format the message first
        formatted = super().format(record)

        # Apply redactions
        if self.redact_phone:
            formatted = self._redact_phone(formatted)
        if self.redact_email:
            formatted = self._redact_email(formatted)
        if self.redact_tokens:
            formatted = self._redact_tokens(formatted)

        return formatted


def configure_pii_safe_logging(
    level: str = "INFO",
    redact_phone: bool = True,
    redact_email: bool = True,
    redact_tokens: bool = True,
) -> None:
    """Configure all loggers to use PII-redacting formatter.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        redact_phone: Whether to redact phone numbers
        redact_email: Whether to redact email addresses
        redact_tokens: Whether to redact API tokens and secrets
    """
    formatter = PIIRedactingFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        redact_phone=redact_phone,
        redact_email=redact_email,
        redact_tokens=redact_tokens,
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Update all handlers to use the PII-redacting formatter
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    # If no handlers exist, add a stream handler
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
