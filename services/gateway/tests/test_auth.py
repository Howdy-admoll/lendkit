"""
API Gateway — JWT Auth Unit Tests

Pure Python — no HTTP, no DB.
"""

import time

import jwt
import pytest

from app.auth.jwt import (
    TokenError,
    create_access_token,
    extract_bearer_token,
    verify_token,
)
from app.core.config import get_settings

settings = get_settings()


# ===========================================================================
# create_access_token
# ===========================================================================


class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        assert isinstance(token, str)

    def test_token_is_valid_jwt(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "user-1"

    def test_tenant_id_in_payload(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["tenant_id"] == "acme"

    def test_default_role_is_admin(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "admin"

    def test_custom_role(self):
        token = create_access_token(subject="agent-1", tenant_id="acme", role="agent")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "agent"

    def test_exp_is_in_future(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["exp"] > int(time.time())

    def test_iat_is_present(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert "iat" in payload

    def test_extra_claims_included(self):
        token = create_access_token(
            subject="user-1", tenant_id="acme", extra_claims={"custom": "value"}
        )
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["custom"] == "value"

    def test_different_subjects_produce_different_tokens(self):
        t1 = create_access_token(subject="user-1", tenant_id="acme")
        t2 = create_access_token(subject="user-2", tenant_id="acme")
        assert t1 != t2


# ===========================================================================
# verify_token
# ===========================================================================


class TestVerifyToken:
    def test_valid_token_returns_payload(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        payload = verify_token(token)
        assert payload["sub"] == "user-1"
        assert payload["tenant_id"] == "acme"

    def test_wrong_secret_raises_token_error(self):
        token = jwt.encode(
            {"sub": "user-1", "tenant_id": "acme", "exp": int(time.time()) + 3600},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(TokenError, match="Invalid token"):
            verify_token(token)

    def test_expired_token_raises_token_error(self):
        token = jwt.encode(
            {"sub": "user-1", "exp": int(time.time()) - 1},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError, match="expired"):
            verify_token(token)

    def test_tampered_payload_raises_token_error(self):
        token = create_access_token(subject="user-1", tenant_id="acme")
        # Flip a character in the payload section
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1][:-1] + "X" + "." + parts[2]
        with pytest.raises(TokenError):
            verify_token(tampered)

    def test_garbage_string_raises_token_error(self):
        with pytest.raises(TokenError):
            verify_token("not.a.jwt")

    def test_empty_string_raises_token_error(self):
        with pytest.raises(TokenError):
            verify_token("")

    def test_role_preserved_after_verify(self):
        token = create_access_token(subject="agent-1", tenant_id="acme", role="agent")
        payload = verify_token(token)
        assert payload["role"] == "agent"


# ===========================================================================
# extract_bearer_token
# ===========================================================================


class TestExtractBearerToken:
    def test_valid_header(self):
        token = extract_bearer_token("Bearer eyJtoken")
        assert token == "eyJtoken"

    def test_case_insensitive_bearer(self):
        token = extract_bearer_token("bearer eyJtoken")
        assert token == "eyJtoken"

    def test_missing_header_raises(self):
        with pytest.raises(TokenError, match="missing"):
            extract_bearer_token(None)

    def test_empty_header_raises(self):
        with pytest.raises(TokenError):
            extract_bearer_token("")

    def test_no_bearer_prefix_raises(self):
        with pytest.raises(TokenError, match="Bearer"):
            extract_bearer_token("eyJtoken")

    def test_extra_parts_raises(self):
        with pytest.raises(TokenError):
            extract_bearer_token("Bearer token extra")
