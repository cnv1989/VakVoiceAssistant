"""
Custom exception classes for VakDeepGram.
"""
from typing import Any, Optional


class VakError(Exception):
    """Base exception for VakDeepGram errors."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        """Convert exception to dictionary for API responses."""
        result = {"error": self.message}
        if self.details:
            result["details"] = self.details
        return result


class SquareAPIError(VakError):
    """Exception for Square API errors."""

    def __init__(
        self,
        message: str,
        errors: Optional[list] = None,
        status_code: Optional[int] = None,
    ):
        super().__init__(message, details=errors)
        self.errors = errors
        self.status_code = status_code

    def to_dict(self) -> dict:
        result = {"error": self.message}
        if self.errors:
            result["square_errors"] = self.errors
        if self.status_code:
            result["status_code"] = self.status_code
        return result


class ValidationError(VakError):
    """Exception for input validation errors."""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.field = field

    def to_dict(self) -> dict:
        result = {"error": self.message}
        if self.field:
            result["field"] = self.field
        return result


class AuthenticationError(VakError):
    """Exception for authentication failures."""

    pass


class ConnectionError(VakError):
    """Exception for connection-related errors."""

    def __init__(self, message: str, connection_id: Optional[str] = None):
        super().__init__(message)
        self.connection_id = connection_id


class BusinessContextError(VakError):
    """Exception for business context resolution failures."""

    def __init__(
        self,
        message: str,
        business_number: Optional[str] = None,
    ):
        super().__init__(message)
        self.business_number = business_number
