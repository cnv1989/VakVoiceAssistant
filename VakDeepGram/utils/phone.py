"""
Phone number normalization and validation utilities.
"""
import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


def normalize_phone_number(value: str) -> Optional[str]:
    """Normalize a phone number to E.164 format (+1XXXXXXXXXX).

    Args:
        value: Phone number string in various formats

    Returns:
        Normalized phone number or None if invalid
    """
    if not value:
        return None

    # Extract digits only
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None

    # Handle US numbers
    if digits.startswith("1") and len(digits) == 11:
        normalized = f"+{digits}"
        logger.debug("Normalized phone number %s -> %s", value, normalized)
        return normalized

    if len(digits) == 10:
        normalized = f"+1{digits}"
        logger.debug("Normalized phone number %s -> %s", value, normalized)
        return normalized

    # Already has country code
    if value.startswith("+"):
        logger.debug("Normalized phone number %s -> %s", value, value)
        return value

    # Default: prepend +
    normalized = f"+{digits}"
    logger.debug("Normalized phone number %s -> %s", value, normalized)
    return normalized


def phone_digit_variants(value: Optional[str]) -> Set[str]:
    """Get all digit variants of a phone number for matching.

    Args:
        value: Phone number string

    Returns:
        Set of digit-only variants for comparison
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        normalized = normalize_phone_number(value or "")
        if not normalized:
            return set()
        digits = "".join(ch for ch in normalized if ch.isdigit())

    variants = {digits} if digits else set()

    # Add variant without country code
    if digits.startswith("1") and len(digits) == 11:
        variants.add(digits[1:])

    # Add variant with country code
    if len(digits) == 10:
        variants.add(f"1{digits}")

    return variants


def candidate_numbers(raw_number: str) -> list[str]:
    """Get candidate digit strings for phone number lookup.

    Args:
        raw_number: Raw phone number input

    Returns:
        List of digit-only candidates for lookup
    """
    normalized = normalize_phone_number(raw_number)
    if not normalized:
        return []

    digits = "".join(ch for ch in normalized if ch.isdigit())

    if digits.startswith("1") and len(digits) == 11:
        return [digits[1:]]
    if len(digits) == 10:
        return [digits]
    return [digits]
