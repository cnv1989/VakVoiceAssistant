import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from providers.clients.setmore import SetmoreApiClient
from providers.clients.square import SquareApiClient
from providers.clients.token_resolver import ensure_provider_access_context


@pytest.mark.asyncio
async def test_token_resolver_setmore_prefers_dynamodb():
    with patch(
        "providers.clients.token_resolver.get_setmore_access_token_from_dynamodb",
        new=AsyncMock(return_value={"success": True, "access_token": "sm-token-from-ddb"}),
    ):
        result = await ensure_provider_access_context(
            business_context={"provider": "setmore", "business_number": "+15550001111"},
        )
    assert result["success"] is True
    assert result["provider"] == "setmore"
    assert result["access_token"] == "sm-token-from-ddb"


@pytest.mark.asyncio
async def test_token_resolver_square_rehydrates_context():
    with patch(
        "providers.clients.token_resolver.resolve_business_context",
        new=AsyncMock(
            return_value={
                "success": True,
                "provider": "square",
                "accessToken": "sq-token",
                "locationId": "LOC123",
            }
        ),
    ):
        result = await ensure_provider_access_context(
            business_context={"provider": "square", "business_number": "+15550001111"},
            require_location=True,
        )
    assert result["success"] is True
    assert result["provider"] == "square"
    assert result["access_token"] == "sq-token"
    assert result["location_id"] == "LOC123"


@pytest.mark.asyncio
async def test_setmore_client_uses_refresh_token():
    with patch(
        "providers.clients.setmore.setmore_api.fetch_services",
        new=AsyncMock(return_value={"success": True, "services": []}),
    ) as mock_fetch:
        client = SetmoreApiClient("token-1", refresh_token="refresh-1")
        result = await client.fetch_services()
    assert result["success"] is True
    mock_fetch.assert_awaited_once_with("token-1", refresh_token="refresh-1")


@pytest.mark.asyncio
async def test_square_client_find_customer_by_phone():
    fake_square = MagicMock()
    fake_square.customers.search = AsyncMock(return_value=object())

    with patch("providers.clients.square.get_square_client", return_value=fake_square), patch(
        "providers.clients.square.parse_square_response",
        return_value={"success": True, "payload": {"customers": [{"id": "C1"}]}},
    ):
        client = SquareApiClient("sq-token")
        customer = await client.find_customer_by_phone("+15105551234")

    assert customer == {"id": "C1"}
    fake_square.customers.search.assert_awaited()

