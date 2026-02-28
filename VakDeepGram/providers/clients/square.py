from __future__ import annotations

from typing import Any, Dict, Optional

from utils.square_client import get_square_client
from utils.square_helpers import parse_square_response
from utils.phone import phone_digit_variants


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


class SquareApiClient:
    """Thin Square client wrapper with a few convenience helpers."""

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self._client = get_square_client(access_token)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def find_customer_by_phone(self, phone: str) -> Optional[dict]:
        variants = phone_digit_variants(phone) or [phone]
        for variant in variants:
            try:
                response = await self._client.customers.search(
                    query={"filter": {"phone_number": {"exact": variant}}}
                )
            except Exception:
                continue
            parsed = parse_square_response(response)
            if not parsed.get("success"):
                continue
            customers = parsed.get("payload", {}).get("customers") or []
            if customers:
                return _as_dict(customers[0])
        return None

    async def create_customer(
        self,
        *,
        idempotency_key: str,
        given_name: str,
        family_name: str,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        response = await self._client.customers.create(
            idempotency_key=idempotency_key,
            given_name=given_name,
            family_name=family_name,
            phone_number=phone_number,
        )
        parsed = parse_square_response(response)
        if not parsed.get("success"):
            return {"success": False, "error": parsed.get("error")}
        return {"success": True, "customer": parsed.get("payload", {}).get("customer")}

