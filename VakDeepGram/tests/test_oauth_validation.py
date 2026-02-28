import jwt

from vakdeepgram.security import oauth


class _FakeSigningKey:
    key = "fake-public-key"


class _FakeJwkClient:
    def get_signing_key_from_jwt(self, _token: str):
        return _FakeSigningKey()


def test_validate_oauth_token_accepts_id_token_aud(monkeypatch):
    monkeypatch.setattr(oauth.config.settings, "oauth_jwks_url", "https://example.com/jwks.json")
    monkeypatch.setattr(oauth.config.settings, "oauth_issuer", "https://issuer.example.com")
    monkeypatch.setattr(oauth.config.settings, "oauth_audience", "client-a")
    monkeypatch.setattr(oauth.config.settings, "oauth_required_scope", None)
    monkeypatch.setattr(oauth, "_get_jwk_client", lambda _url: _FakeJwkClient())
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: {"sub": "u1", "iss": "https://issuer.example.com", "aud": "client-a", "token_use": "id"},
    )

    result = oauth.validate_oauth_token("fake-token")
    assert result["success"] is True
    assert result["claims"]["token_use"] == "id"


def test_validate_oauth_token_accepts_access_token_client_id(monkeypatch):
    monkeypatch.setattr(oauth.config.settings, "oauth_jwks_url", "https://example.com/jwks.json")
    monkeypatch.setattr(oauth.config.settings, "oauth_issuer", "https://issuer.example.com")
    monkeypatch.setattr(oauth.config.settings, "oauth_audience", "client-a")
    monkeypatch.setattr(oauth.config.settings, "oauth_required_scope", None)
    monkeypatch.setattr(oauth, "_get_jwk_client", lambda _url: _FakeJwkClient())
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "u1",
            "iss": "https://issuer.example.com",
            "client_id": "client-a",
            "token_use": "access",
        },
    )

    result = oauth.validate_oauth_token("fake-token")
    assert result["success"] is True
    assert result["claims"]["token_use"] == "access"


def test_validate_oauth_token_supports_multiple_audiences(monkeypatch):
    monkeypatch.setattr(oauth.config.settings, "oauth_jwks_url", "https://example.com/jwks.json")
    monkeypatch.setattr(oauth.config.settings, "oauth_issuer", "https://issuer.example.com")
    monkeypatch.setattr(oauth.config.settings, "oauth_audience", "client-a,client-b")
    monkeypatch.setattr(oauth.config.settings, "oauth_required_scope", None)
    monkeypatch.setattr(oauth, "_get_jwk_client", lambda _url: _FakeJwkClient())
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: {"sub": "u1", "iss": "https://issuer.example.com", "aud": "client-b"},
    )

    result = oauth.validate_oauth_token("fake-token")
    assert result["success"] is True


def test_validate_oauth_token_rejects_audience_mismatch(monkeypatch):
    monkeypatch.setattr(oauth.config.settings, "oauth_jwks_url", "https://example.com/jwks.json")
    monkeypatch.setattr(oauth.config.settings, "oauth_issuer", "https://issuer.example.com")
    monkeypatch.setattr(oauth.config.settings, "oauth_audience", "client-a")
    monkeypatch.setattr(oauth.config.settings, "oauth_required_scope", None)
    monkeypatch.setattr(oauth, "_get_jwk_client", lambda _url: _FakeJwkClient())
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: {"sub": "u1", "iss": "https://issuer.example.com", "aud": "client-x"},
    )

    result = oauth.validate_oauth_token("fake-token")
    assert result["success"] is False
    assert "audience" in result["error"].lower() or "client_id" in result["error"].lower()
