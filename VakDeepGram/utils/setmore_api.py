import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx

from vakdeepgram import config
from utils.retry import run_async_with_retry
from utils.metrics import emit_api_metrics

logger = logging.getLogger(__name__)

# Raised for 5xx responses so retry with backoff can run
class SetmoreServerError(Exception):
    """Setmore API returned a server error (5xx)."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        self.message = message or f"Setmore API error {status_code}"
        super().__init__(self.message)

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


# Transient errors we retry with exponential backoff
_SETMORE_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)


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
    start = time.monotonic()
    response: Optional[httpx.Response] = None

    async def _fetch() -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url, params=params)

    try:
        response = await run_async_with_retry(_fetch, retry_exceptions=_SETMORE_RETRY_EXCEPTIONS)
    except Exception as e:
        logger.error("Setmore token request failed after retries: %s", e)
        emit_api_metrics(
            "setmore",
            "GET /o/oauth2/token",
            (time.monotonic() - start) * 1000,
            False,
            error_type=type(e).__name__,
        )
        return {"success": False, "error": str(e)}

    try:
        payload = response.json()
    except Exception:
        logger.error("Failed to decode Setmore token response (%s)", response.text)
        emit_api_metrics(
            "setmore",
            "GET /o/oauth2/token",
            (time.monotonic() - start) * 1000,
            False,
            status_code=response.status_code if response else None,
            error_type="InvalidResponse",
        )
        return {"success": False, "error": "Invalid Setmore token response."}

    parsed = _parse_response(payload)
    if not parsed.get("success"):
        emit_api_metrics(
            "setmore",
            "GET /o/oauth2/token",
            (time.monotonic() - start) * 1000,
            False,
            status_code=response.status_code if response else None,
            error_type="SetmoreApiError",
        )
        return {"success": False, "error": parsed.get("error")}

    token_payload = (parsed.get("data") or {}).get("token") or {}
    access_token = token_payload.get("access_token")
    if not access_token:
        emit_api_metrics(
            "setmore",
            "GET /o/oauth2/token",
            (time.monotonic() - start) * 1000,
            False,
            status_code=response.status_code if response else None,
            error_type="MissingAccessToken",
        )
        return {"success": False, "error": "Setmore access token missing."}
    expires_in = token_payload.get("expires_in") or 0
    user_id = token_payload.get("user_id")
    new_refresh_token = token_payload.get("refresh_token")
    expires_at = now + int(expires_in) if expires_in else now + 3600
    cache_refresh = new_refresh_token or refresh_token
    _TOKEN_CACHE[cache_refresh] = {
        "access_token": access_token,
        "expires_in": expires_in,
        "user_id": user_id,
        "expires_at": expires_at,
    }
    result = {
        "success": True,
        "access_token": access_token,
        "expires_in": expires_in,
        "user_id": user_id,
        "cached": False,
    }
    if new_refresh_token:
        result["refresh_token"] = new_refresh_token
    result["expires_at"] = expires_at
    emit_api_metrics(
        "setmore",
        "GET /o/oauth2/token",
        (time.monotonic() - start) * 1000,
        True,
        status_code=response.status_code if response else None,
    )
    return result


def _invalidate_token_cache(refresh_token: str) -> None:
    """Remove a cached token so the next get_access_token() forces a refresh."""
    _TOKEN_CACHE.pop(refresh_token, None)


def _is_unauthorized(response: httpx.Response, payload: Any) -> bool:
    """Detect a 401/unauthorized response from Setmore (HTTP status or body)."""
    if response.status_code == 401:
        return True
    if isinstance(payload, dict):
        err = payload.get("error") or payload.get("msg") or ""
        if isinstance(err, str) and "unauthorized" in err.lower():
            return True
    return False


async def request(
    method: str,
    path: str,
    access_token: str,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    *,
    refresh_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Make a Setmore API request with exponential backoff retries and optional 401 retry.

    Retries on connection errors, timeouts, and 5xx with exponential backoff (up to 5 attempts).
    If *refresh_token* is provided and the first request returns 401 / unauthorized,
    the token cache is invalidated, a fresh access token is obtained, and the request is retried once.
    """
    url = _booking_url(path)
    timeout = config.settings.setmore_request_timeout_seconds
    start = time.monotonic()
    api_name = f"{method} {path}"
    response: Optional[httpx.Response] = None

    async def _do_request(token: str) -> Tuple[httpx.Response, Any]:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json, headers=headers)
        if resp.status_code >= 500:
            raise SetmoreServerError(resp.status_code, resp.text[:200] or "")
        try:
            body = resp.json()
        except Exception:
            body = None
        return resp, body

    retry_exceptions: tuple = _SETMORE_RETRY_EXCEPTIONS + (SetmoreServerError,)

    async def _do_request_with_retry(token: str) -> Tuple[httpx.Response, Any]:
        return await run_async_with_retry(
            lambda: _do_request(token),
            retry_exceptions=retry_exceptions,
        )

    # --- first attempt (with backoff retries) ---
    try:
        response, payload = await _do_request_with_retry(access_token)
    except SetmoreServerError as e:
        logger.error("Setmore API 5xx after retries: %s %s — %s", method, path, e)
        emit_api_metrics(
            "setmore",
            api_name,
            (time.monotonic() - start) * 1000,
            False,
            error_type=type(e).__name__,
        )
        return {"success": False, "error": e.message}
    except Exception as e:
        logger.error("Setmore API request failed after retries: %s %s — %s", method, path, e)
        emit_api_metrics(
            "setmore",
            api_name,
            (time.monotonic() - start) * 1000,
            False,
            error_type=type(e).__name__,
        )
        return {"success": False, "error": str(e)}

    # --- 401 retry (one token refresh, then same backoff retries) ---
    if refresh_token and _is_unauthorized(response, payload):
        logger.warning(
            "[SetmoreAPI] Got unauthorized on %s %s — refreshing token and retrying",
            method, path,
        )
        _invalidate_token_cache(refresh_token)
        token_result = await get_access_token(refresh_token)
        if token_result.get("success"):
            new_token = token_result["access_token"]
            try:
                response, payload = await _do_request_with_retry(new_token)
            except SetmoreServerError as e:
                emit_api_metrics(
                    "setmore",
                    api_name,
                    (time.monotonic() - start) * 1000,
                    False,
                    error_type=type(e).__name__,
                )
                return {"success": False, "error": e.message}
            except Exception as e:
                emit_api_metrics(
                    "setmore",
                    api_name,
                    (time.monotonic() - start) * 1000,
                    False,
                    error_type=type(e).__name__,
                )
                return {"success": False, "error": str(e)}
        else:
            emit_api_metrics(
                "setmore",
                api_name,
                (time.monotonic() - start) * 1000,
                False,
                error_type="TokenRefreshFailed",
            )
            return {"success": False, "error": token_result.get("error") or "Token refresh failed"}

    if payload is None:
        logger.error("Failed to decode Setmore response (%s)", response.text)
        emit_api_metrics(
            "setmore",
            api_name,
            (time.monotonic() - start) * 1000,
            False,
            status_code=response.status_code if response else None,
            error_type="InvalidResponse",
        )
        return {"success": False, "error": "Invalid Setmore response."}

    parsed = _parse_response(payload)
    if not parsed.get("success"):
        emit_api_metrics(
            "setmore",
            api_name,
            (time.monotonic() - start) * 1000,
            False,
            status_code=response.status_code if response else None,
            error_type="SetmoreApiError",
        )
        return {"success": False, "error": parsed.get("error")}
    emit_api_metrics(
        "setmore",
        api_name,
        (time.monotonic() - start) * 1000,
        True,
        status_code=response.status_code if response else None,
    )
    return {"success": True, "data": parsed.get("data")}


async def fetch_services(access_token: str, *, refresh_token: Optional[str] = None) -> Dict[str, Any]:
    result = await request("GET", "/bookingapi/services", access_token, refresh_token=refresh_token)
    if not result.get("success"):
        return result
    services = (result.get("data") or {}).get("services") or []
    return {"success": True, "services": services}


async def fetch_service_categories(access_token: str, *, refresh_token: Optional[str] = None) -> Dict[str, Any]:
    result = await request("GET", "/bookingapi/services/categories", access_token, refresh_token=refresh_token)
    if not result.get("success"):
        return result
    raw = (result.get("data") or {}).get("service_categories") or []
    all_categories = []
    for cat in raw:
        all_categories.append({
            "key": cat.get("key") or cat.get("category_key") or "",
            "category_name": cat.get("category_name") or cat.get("categoryName") or "Uncategorized",
            "service_id_list": (
                cat.get("service_id_list")
                if isinstance(cat.get("service_id_list"), list)
                else cat.get("serviceIdList")
                if isinstance(cat.get("serviceIdList"), list)
                else []
            ),
        })
    # Setmore returns a default "All Services" umbrella; exclude it when real
    # categories exist so services are grouped by their meaningful category.
    specific = [
        c for c in all_categories
        if c["category_name"].lower() != "all services"
    ]
    categories = specific if specific else all_categories
    return {"success": True, "service_categories": categories}


async def fetch_staff(access_token: str, *, refresh_token: Optional[str] = None) -> Dict[str, Any]:
    staffs: list[Dict[str, Any]] = []
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else None
        result = await request("GET", "/bookingapi/staffs", access_token, params=params, refresh_token=refresh_token)
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
    *,
    refresh_token: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"firstname": first_name}
    if phone:
        params["phone"] = phone
    if email:
        params["email"] = email
    result = await request("GET", "/bookingapi/customer", access_token, params=params, refresh_token=refresh_token)
    if not result.get("success"):
        return result
    customers = (result.get("data") or {}).get("customer") or []
    return {"success": True, "customers": customers}


async def create_customer(access_token: str, payload: Dict[str, Any], *, refresh_token: Optional[str] = None) -> Dict[str, Any]:
    result = await request("POST", "/bookingapi/customer/create", access_token, json=payload, refresh_token=refresh_token)
    if not result.get("success"):
        return result
    customer = (result.get("data") or {}).get("customer")
    return {"success": True, "customer": customer}


async def fetch_slots(access_token: str, payload: Dict[str, Any], *, refresh_token: Optional[str] = None) -> Dict[str, Any]:
    result = await request("POST", "/bookingapi/slots", access_token, json=payload, refresh_token=refresh_token)
    if not result.get("success"):
        return result
    data = result.get("data")
    slots = _extract_list(data) or []
    if not slots and data is not None:
        logger.debug("Setmore slots API returned no list; raw data: %s", data)
    return {"success": True, "slots": slots}


def _normalize_booking_page_url(raw: str) -> str:
    """Ensure the booking page URL is a full https://…setmore.com URL."""
    val = (raw or "").strip().rstrip("/")
    if not val:
        return val
    if re.match(r"^https?://", val, re.IGNORECASE):
        return val
    if ".setmore.com" in val.lower():
        return f"https://{val}"
    return f"https://{val}.setmore.com"


def generate_booking_link(
    booking_page_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a prefilled Setmore booking link from the given payload. Does not create an appointment.

    Payload may include: service_key, staff_key, start_time (YYYY-MM-DDTHH:MM or ISO), customer_key.
    """
    normalized = _normalize_booking_page_url(booking_page_url)
    if not normalized:
        return {"success": False, "error": "Missing booking page URL."}
    parsed = urlparse(normalized.rstrip("/"))
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    if not path.endswith("/book"):
        path = f"{path}/book" if path else "/book"

    params: Dict[str, str] = {"step": "user-details", "type": "service"}
    if payload.get("service_key"):
        params["products"] = str(payload["service_key"])
    if payload.get("staff_key"):
        params["staff"] = str(payload["staff_key"])
        params["staffSelected"] = "true"
    if payload.get("customer_key"):
        params["customer"] = str(payload["customer_key"])

    start_time = payload.get("start_time")
    if start_time:
        try:
            if isinstance(start_time, str):
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                dt = start_time
            epoch_ms = int(dt.timestamp() * 1000)
            params["slot"] = str(epoch_ms)
        except (ValueError, TypeError, AttributeError):
            pass

    booking_url = f"{base}{path}?{urlencode(params)}"
    return {"success": True, "booking_url": booking_url}


async def fetch_appointments(
    access_token: str,
    start_date: str,
    end_date: str,
    staff_key: Optional[str] = None,
    customer_details: bool = False,
    *,
    refresh_token: Optional[str] = None,
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
        result = await request("GET", "/bookingapi/appointments", access_token, params=params, refresh_token=refresh_token)
        if not result.get("success"):
            return result
        data = result.get("data") or {}
        appointments.extend(data.get("appointments") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return {"success": True, "appointments": appointments}
