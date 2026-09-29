from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, ValidationFailed
from app.core.logging import redact, redact_obj
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_str,
    encrypt_str,
    hash_password,
    token_digest,
    validate_password_strength,
    verify_password,
)


def test_password_hashing_roundtrip() -> None:
    h = hash_password("Str0ng!Passw0rd")
    assert h.startswith("$argon2")
    assert verify_password("Str0ng!Passw0rd", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", None)


@pytest.mark.parametrize("pw", ["short1!A", "alllowercaseletters", "NoDigitsOrSymbolsHere"])
def test_password_policy_rejects_weak(pw: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_password_strength(pw)


def test_jwt_roundtrip_and_tampering() -> None:
    uid, oid = uuid.uuid4(), uuid.uuid4()
    tok = create_access_token(user_id=uid, org_id=oid, roles=["recruiter"])
    claims = decode_access_token(tok)
    assert claims["sub"] == str(uid) and claims["org"] == str(oid)
    header, payload, sig = tok.split(".")
    with pytest.raises(AuthenticationError):
        decode_access_token(f"{header}.{payload}.{sig[::-1]}")
    forged = jwt.encode({**claims, "roles": ["super_admin"]}, "attacker-key", algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)
    none_alg = jwt.encode({**claims}, None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(AuthenticationError):
        decode_access_token(none_alg)


def test_expired_and_wrong_type_tokens_rejected() -> None:
    s = get_settings()
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "x", "iat": now - 100, "exp": now - 10, "iss": s.jwt_issuer, "aud": s.jwt_audience, "typ": "access"},
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError, match="expired"):
        decode_access_token(expired)
    magic = jwt.encode(
        {"sub": "x", "iat": now, "exp": now + 60, "iss": s.jwt_issuer, "aud": s.jwt_audience, "typ": "magic"},
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(magic)


def test_field_encryption_and_digest() -> None:
    ct = encrypt_str("+27 82 555 1234")
    assert "555" not in ct and decrypt_str(ct) == "+27 82 555 1234"
    assert token_digest("abc") == token_digest("abc") != token_digest("abd")


def test_log_redaction() -> None:
    text = "Contact jane@example.com or +27 82 555 1234 with Bearer abc.def.ghi and sk-ant-1234567890abc"
    out = redact(text)
    assert "jane@example.com" not in out and "555 1234" not in out and "abc.def.ghi" not in out
    assert "sk-ant" not in out
    assert redact_obj({"password": "x", "nested": {"token": "y", "note": "a@b.co"}}) == {
        "password": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "note": "[REDACTED_EMAIL]"},
    }


def test_production_requires_real_secrets() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production")
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        Settings(environment="production", jwt_secret="x" * 40)  # type: ignore[arg-type]
