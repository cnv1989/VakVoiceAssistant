"""
Tests for phone number normalization utilities.
"""
import pytest
from utils.phone import normalize_phone_number, phone_digit_variants, candidate_numbers


class TestNormalizePhoneNumber:
    """Tests for normalize_phone_number function."""

    def test_empty_value(self):
        assert normalize_phone_number("") is None
        assert normalize_phone_number(None) is None

    def test_10_digit_us_number(self):
        result = normalize_phone_number("5551234567")
        assert result == "+15551234567"

    def test_11_digit_us_number(self):
        result = normalize_phone_number("15551234567")
        assert result == "+15551234567"

    def test_formatted_us_number(self):
        result = normalize_phone_number("(555) 123-4567")
        assert result == "+15551234567"

    def test_dashed_number(self):
        result = normalize_phone_number("555-123-4567")
        assert result == "+15551234567"

    def test_number_with_plus(self):
        result = normalize_phone_number("+15551234567")
        assert result == "+15551234567"

    def test_number_with_spaces(self):
        result = normalize_phone_number("555 123 4567")
        assert result == "+15551234567"

    def test_international_number(self):
        result = normalize_phone_number("+442071234567")
        assert result == "+442071234567"

    def test_non_numeric_input(self):
        result = normalize_phone_number("abc")
        assert result is None


class TestPhoneDigitVariants:
    """Tests for phone_digit_variants function."""

    def test_10_digit_number(self):
        variants = phone_digit_variants("5551234567")
        assert "5551234567" in variants
        assert "15551234567" in variants

    def test_11_digit_number(self):
        variants = phone_digit_variants("15551234567")
        assert "5551234567" in variants
        assert "15551234567" in variants

    def test_formatted_number(self):
        variants = phone_digit_variants("(555) 123-4567")
        assert "5551234567" in variants

    def test_empty_value(self):
        variants = phone_digit_variants("")
        assert variants == set()

    def test_none_value(self):
        variants = phone_digit_variants(None)
        assert variants == set()


class TestCandidateNumbers:
    """Tests for candidate_numbers function."""

    def test_10_digit_number(self):
        candidates = candidate_numbers("5551234567")
        assert "5551234567" in candidates

    def test_11_digit_number(self):
        candidates = candidate_numbers("15551234567")
        assert "5551234567" in candidates

    def test_formatted_number(self):
        candidates = candidate_numbers("(555) 123-4567")
        assert "5551234567" in candidates

    def test_empty_value(self):
        candidates = candidate_numbers("")
        assert candidates == []
