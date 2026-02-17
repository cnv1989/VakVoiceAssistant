"""
Utilities package for VakDeepGram
"""
from utils.phone import normalize_phone_number, phone_digit_variants, candidate_numbers
from utils.square_helpers import (
    get_square_environment,
    parse_square_response,
    extract_square_cursor,
)
from utils.errors import (
    VakError,
    SquareAPIError,
    ValidationError,
    AuthenticationError,
    ConnectionError,
    BusinessContextError,
)
from utils.logging import PIIRedactingFormatter, configure_pii_safe_logging
from utils.case import to_snake_case, to_snake_case_key

__all__ = [
    # Phone utilities
    "normalize_phone_number",
    "phone_digit_variants",
    "candidate_numbers",
    # Square helpers
    "get_square_environment",
    "parse_square_response",
    "extract_square_cursor",
    # Errors
    "VakError",
    "SquareAPIError",
    "ValidationError",
    "AuthenticationError",
    "ConnectionError",
    "BusinessContextError",
    # Logging
    "PIIRedactingFormatter",
    "configure_pii_safe_logging",
    # Case helpers
    "to_snake_case",
    "to_snake_case_key",
]
