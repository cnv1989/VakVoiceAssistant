import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

import config

logger = logging.getLogger(__name__)

_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _base_url() -> str:
    return config.settings.setmore_api_base_url.rstrip("/")


def _token_url() -> str:
    return f"{_base_url()}/o/oauth2/token"


def _booking_url(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{_base_url()}{path}"


def _parse_response(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"success": False, "error": "Unexpected Setmore response type."}
    if payload.get("response") is True:
        return {"success": True, "data": payload.get("data"), "msg": payload.get("msg")}
    return {"success": False, "error": payload.get("msg") or payload}


def _extract_list(data: Any) -> Optional[list]:
    if data is None:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    return None


async def get_access_token(refresh_token: str) -> Dict[str, Any]:
    if not refresh_token:
        return {"success": False, "error": "Missing Setmore refresh token."}

    cached = _TOKEN_CACHE.get(refresh_token)
    now = _now()
    if cached and cached.get("expires_at", 0) > now + 60:
        return {
            "success": True,
            "access_token": cached.get("access_token"),
            "expires_in": cached.get("expires_in"),
            "user_id": cached.get("user_id"),
            "cached": True,
        }

    url = _token_url()
    params = {"refreshToken": refresh_token}
    timeout = config.settings.setmore_request_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, params=params)
    try:
        payload = response.json()
    except Exception:
        logger.error("Failed to decode Setmore token response (%s)", response.text)
        return {"success": False, "error": "Invalid Setmore token response."}

    parsed = _parse_response(payload)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}

    token_payload = (parsed.get("data") or {}).get("token") or {}
    access_token = token_payload.get("access_token")
    if not access_token:
        return {"success": False, "error": "Setmore access token missing."}
    expires_in = token_payload.get("expires_in") or 0
    user_id = token_payload.get("user_id")
    expires_at = now + int(expires_in) if expires_in else now + 3600
    _TOKEN_CACHE[refresh_token] = {
        "access_token": access_token,
        "expires_in": expires_in,
        "user_id": user_id,
        "expires_at": expires_at,
    }
    return {
        "success": True,
        "access_token": access_token,
        "expires_in": expires_in,
        "user_id": user_id,
        "cached": False,
    }


async def request(
    method: str,
    path: str,
    access_token: str,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = _booking_url(path)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    timeout = config.settings.setmore_request_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, params=params, json=json, headers=headers)
    try:
        payload = response.json()
    except Exception:
        logger.error("Failed to decode Setmore response (%s)", response.text)
        return {"success": False, "error": "Invalid Setmore response."}
    parsed = _parse_response(payload)
    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error")}
    return {"success": True, "data": parsed.get("data")}


async def fetch_services(access_token: str) -> Dict[str, Any]:
    result = await request("GET", "/bookingapi/services", access_token)
    if not result.get("success"):
        return result
    services = (result.get("data") or {}).get("services") or []
    return {"success": True, "services": services}


async def fetch_staff(access_token: str) -> Dict[str, Any]:
    staffs: list[Dict[str, Any]] = []
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else None
        result = await request("GET", "/bookingapi/staffs", access_token, params=params)
        if not result.get("success"):
            return result
        data = result.get("data") or {}
        staffs.extend(data.get("staffs") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return {"success": True, "staffs": staffs}


async def fetch_customer(
    access_token: str,
    first_name: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"firstname": first_name}
    if phone:
        params["phone"] = phone
    if email:
        params["email"] = email
    result = await request("GET", "/bookingapi/customer", access_token, params=params)
    if not result.get("success"):
        return result
    customers = (result.get("data") or {}).get("customer") or []
    return {"success": True, "customers": customers}


async def create_customer(access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = await request("POST", "/bookingapi/customer/create", access_token, json=payload)
    if not result.get("success"):
        return result
    customer = (result.get("data") or {}).get("customer")
    return {"success": True, "customer": customer}


async def fetch_slots(access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = await request("POST", "/bookingapi/slots", access_token, json=payload)
    if not result.get("success"):
        return result
    data = result.get("data")
    slots = _extract_list(data) or []
    return {"success": True, "slots": slots}


async def create_appointment(access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = await request("POST", "/bookingapi/appointment/create", access_token, json=payload)
    if not result.get("success"):
        return result
    appointment = (result.get("data") or {}).get("appointment")
    return {"success": True, "appointment": appointment}


async def fetch_appointments(
    access_token: str,
    start_date: str,
    end_date: str,
    staff_key: Optional[str] = None,
    customer_details: bool = False,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
    }
    if staff_key:
        params["staff_key"] = staff_key
    if customer_details:
        params["customerDetails"] = "true"

    appointments: list[Dict[str, Any]] = []
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        result = await request("GET", "/bookingapi/appointments", access_token, params=params)
        if not result.get("success"):
            return result
        data = result.get("data") or {}
        appointments.extend(data.get("appointments") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return {"success": True, "appointments": appointments}
