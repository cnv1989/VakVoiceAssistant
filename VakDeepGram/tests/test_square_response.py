"""
Tests for Square response parsing utilities.
"""
import pytest
from unittest.mock import MagicMock
from utils.square_helpers import parse_square_response, extract_square_cursor


class TestParseSquareResponse:
    """Tests for parse_square_response function."""

    def test_success_response_with_is_error(self, mock_square_response_success):
        result = parse_square_response(mock_square_response_success)
        assert result["success"] is True
        assert "payload" in result
        assert result["payload"]["customer"]["id"] == "CUST123"

    def test_error_response_with_is_error(self, mock_square_response_error):
        result = parse_square_response(mock_square_response_error)
        assert result["success"] is False
        assert "error" in result

    def test_dict_response_success(self):
        response = {"customer": {"id": "CUST123"}}
        result = parse_square_response(response)
        assert result["success"] is True
        assert result["payload"]["customer"]["id"] == "CUST123"

    def test_dict_response_with_errors(self):
        response = {"errors": [{"code": "NOT_FOUND"}]}
        result = parse_square_response(response)
        assert result["success"] is False
        assert "error" in result

    def test_pydantic_model_success(self):
        class MockModel:
            def model_dump(self):
                return {"customer": {"id": "CUST123"}}

        result = parse_square_response(MockModel())
        assert result["success"] is True

    def test_pydantic_model_with_errors(self):
        class MockModel:
            def model_dump(self):
                return {"errors": [{"code": "ERROR"}]}

        result = parse_square_response(MockModel())
        assert result["success"] is False

    def test_unexpected_type(self):
        result = parse_square_response("unexpected string")
        assert result["success"] is False
        assert "Unexpected" in result["error"]


class TestExtractSquareCursor:
    """Tests for extract_square_cursor function."""

    def test_cursor_in_response(self):
        response = MagicMock()
        response._response = MagicMock()
        response._response.cursor = "CURSOR123"
        result = extract_square_cursor(response)
        assert result == "CURSOR123"

    def test_no_cursor(self):
        response = MagicMock(spec=[])
        result = extract_square_cursor(response)
        assert result is None

    def test_cursor_in_response_attribute(self):
        response = MagicMock()
        response.response = MagicMock()
        response.response.cursor = "CURSOR456"
        del response._response
        result = extract_square_cursor(response)
        assert result == "CURSOR456"
