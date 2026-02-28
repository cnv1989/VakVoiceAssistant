"""
OAuth/JWT validation helpers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import jwt

from vakdeepgram import config

_JWK_CLIENTS: dict[str, jwt.PyJWKClient] = {}


def _get_jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    client = _JWK_CLIENTS.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(jwks_url)
        _JWK_CLIENTS[jwks_url] = client
    return client


def _scopes(payload: Dict[str, Any]) -> set[str]:
    scope_value = payload.get("scope") or payload.get("scp")
    if isinstance(scope_value, str):
        return {part.strip() for part in scope_value.split() if part.strip()}
    if isinstance(scope_value, list):
        return {str(part).strip() for part in scope_value if str(part).strip()}
    return set()


def _audience_values(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part.strip()}


def _claim_matches_audience(claim_value: Any, audiences: set[str]) -> bool:
    if not audiences:
        return True
    if isinstance(claim_value, str):
        return claim_value in audiences
    if isinstance(claim_value, list):
        return any(str(item) in audiences for item in claim_value)
    return False


def validate_oauth_token(token: str) -> Dict[str, Any]:
    """Validate OAuth bearer token using configured JWKS/issuer/audience."""
    jwks_url = config.settings.oauth_jwks_url
    if not jwks_url:
        return {"success": False, "error": "OAuth is not configured (missing oauth_jwks_url)."}

    issuer = config.settings.oauth_issuer
    audiences = _audience_values(config.settings.oauth_audience)
    required_scope = config.settings.oauth_required_scope

    try:
        jwk_client = _get_jwk_client(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=issuer,
            options={"verify_aud": False},
        )
        if audiences:
            aud_match = _claim_matches_audience(payload.get("aud"), audiences)
            client_id_match = _claim_matches_audience(payload.get("client_id"), audiences)
            if not (aud_match or client_id_match):
                return {"success": False, "error": "Token audience/client_id does not match configured oauth_audience."}
        if required_scope and required_scope not in _scopes(payload):
            return {"success": False, "error": f"Missing required scope: {required_scope}"}
        return {"success": True, "claims": payload}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
