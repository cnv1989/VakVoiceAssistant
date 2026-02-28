from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from utils import setmore_api


class SetmoreApiClient:
    """Thin Setmore API client bound to an access token + optional refresh token."""

    def __init__(self, access_token: str, refresh_token: Optional[str] = None) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    async def fetch_services(self) -> Dict[str, Any]:
        return await setmore_api.fetch_services(self.access_token, refresh_token=self.refresh_token)

    async def fetch_service_categories(self) -> Dict[str, Any]:
        return await setmore_api.fetch_service_categories(self.access_token, refresh_token=self.refresh_token)

    async def fetch_staff(self) -> Dict[str, Any]:
        return await setmore_api.fetch_staff(self.access_token, refresh_token=self.refresh_token)

    async def fetch_customer(
        self,
        *,
        first_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await setmore_api.fetch_customer(
            self.access_token,
            first_name=first_name,
            phone=phone,
            email=email,
            refresh_token=self.refresh_token,
        )

    async def create_customer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await setmore_api.create_customer(
            self.access_token,
            payload,
            refresh_token=self.refresh_token,
        )

    async def fetch_slots(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await setmore_api.fetch_slots(
            self.access_token,
            payload,
            refresh_token=self.refresh_token,
        )

    async def fetch_appointments(
        self,
        *,
        start_date: str,
        end_date: str,
        customer_details: bool = True,
    ) -> Dict[str, Any]:
        return await setmore_api.fetch_appointments(
            self.access_token,
            start_date=start_date,
            end_date=end_date,
            customer_details=customer_details,
            refresh_token=self.refresh_token,
        )

    @staticmethod
    def generate_booking_link(
        booking_page_url: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return setmore_api.generate_booking_link(booking_page_url, payload)

    @staticmethod
    def build_booking_url(
        booking_page_url: str,
        service_key: Optional[str] = None,
        staff_key: Optional[str] = None,
        start_dt: Optional[datetime] = None,
        customer_key: Optional[str] = None,
    ) -> str:
        return setmore_api.build_booking_url(
            booking_page_url=booking_page_url,
            service_key=service_key,
            staff_key=staff_key,
            start_dt=start_dt,
            customer_key=customer_key,
        )
