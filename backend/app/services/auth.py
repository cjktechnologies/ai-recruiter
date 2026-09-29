"""Authentication: password login, refresh-token rotation with reuse detection, candidate magic
links and OpenID Connect SSO."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError, ExternalServiceError
from app.core.principal import Principal
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    new_opaque_token,
    token_digest,
    verify_password,
)
from app.domain.enums import ActorType
from app.domain.permissions import Role
from app.models.candidates import Candidate
from app.models.org import Organization, RefreshToken, RoleDef, User
from app.services.audit import audit

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def user_permissions(user: User) -> frozenset[str]:
    perms: set[str] = set()
    for r in user.roles:
        perms |= set(r.permissions)
    return frozenset(perms)


def issue_tokens(db: Session, user: User, *, family_id: uuid.UUID | None = None, user_agent: str | None = None) -> dict:
    s = get_settings()
    access = create_access_token(user_id=user.id, org_id=user.organization_id, roles=user.role_keys)
    refresh = new_opaque_token(48)
    now = _now()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_digest(refresh),
            family_id=family_id or uuid.uuid4(),
            issued_at=now,
            expires_at=now + timedelta(days=s.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:400],
        )
    )
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": s.access_token_ttl_minutes * 60,
    }


def login(db: Session, email: str, password: str, *, ip: str | None, user_agent: str | None) -> dict:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    now = _now()
    if user and user.locked_until and user.locked_until > now:
        raise AuthenticationError("Account temporarily locked. Try again later.")
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_count = 0
            audit(
                db,
                action="auth.login_failed",
                entity_type="user",
                entity_id=user.id,
                organization_id=user.organization_id,
                actor_type=ActorType.SYSTEM,
                changes={"ip": ip},
            )
            db.commit()
        raise AuthenticationError("Invalid credentials")
    if user.organization_id:
        org = db.get(Organization, user.organization_id)
        if not org or not org.is_active:
            raise AuthenticationError("Organization is disabled")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = issue_tokens(db, user, user_agent=user_agent)
    audit(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_type=ActorType.USER,
        actor_id=str(user.id),
        changes={"ip": ip},
    )
    return tokens


def refresh(db: Session, refresh_token: str, *, user_agent: str | None) -> dict:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(refresh_token)))
    now = _now()
    if not row:
        raise AuthenticationError("Invalid refresh token")
    if row.revoked_at is not None:
        # Reuse of a rotated token → likely theft: revoke the whole family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise AuthenticationError("Refresh token reuse detected; please sign in again")
    if row.expires_at < now:
        raise AuthenticationError("Refresh token expired")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise AuthenticationError("User inactive")
    row.revoked_at = now
    return issue_tokens(db, user, family_id=row.family_id, user_agent=user_agent)


def logout(db: Session, refresh_token: str) -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(refresh_token)))
    if row and row.revoked_at is None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )


def principal_from_token(
    db: Session, token: str, *, org_override: str | None, ip: str | None, user_agent: str | None
) -> Principal:
    claims = decode_access_token(token)
    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise AuthenticationError("Invalid token subject") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise AuthenticationError("User inactive or not found")
    roles = tuple(user.role_keys)
    org_id = user.organization_id
    if Role.SUPER_ADMIN.value in roles and org_override:
        try:
            org_id = uuid.UUID(org_override)
        except ValueError as exc:
            raise AuthenticationError("Invalid X-Organization-Id") from exc
        if not db.get(Organization, org_id):
            raise AuthenticationError("Unknown organization")
    if org_id is None:
        # Super admin without a selected tenant: platform-level operations only.
        org_id = uuid.UUID(int=0)
    return Principal(
        user_id=user.id,
        organization_id=org_id,
        roles=roles,
        permissions=user_permissions(user),
        email=user.email,
        candidate_id=user.candidate_id,
        ip_address=ip,
        user_agent=user_agent,
    )


# --- Candidate portal: passwordless magic links --------------------------------------
def create_candidate_magic_token(db: Session, org: Organization, email: str) -> str | None:
    cand = db.scalar(
        select(Candidate).where(
            Candidate.organization_id == org.id, Candidate.email == email.lower(), Candidate.anonymized_at.is_(None)
        )
    )
    if not cand:
        return None  # caller responds identically either way (no account enumeration)
    s = get_settings()
    return jwt.encode(
        {
            "typ": "magic",
            "cand": str(cand.id),
            "org": str(org.id),
            "exp": _now() + timedelta(minutes=20),
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": secrets.token_hex(8),
        },
        s.jwt_secret.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )


def exchange_candidate_magic_token(db: Session, token: str) -> dict:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[s.jwt_algorithm],
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired link") from exc
    if claims.get("typ") != "magic":
        raise AuthenticationError("Invalid link")
    cand = db.get(Candidate, uuid.UUID(claims["cand"]))
    if not cand or str(cand.organization_id) != claims["org"] or cand.anonymized_at:
        raise AuthenticationError("Invalid link")
    user = db.scalar(select(User).where(User.candidate_id == cand.id))
    if not user:
        role = db.scalar(select(RoleDef).where(RoleDef.key == Role.CANDIDATE.value, RoleDef.organization_id.is_(None)))
        user = User(
            organization_id=cand.organization_id,
            email=f"candidate+{cand.id}@portal.invalid",
            full_name=cand.full_name,
            auth_provider="magic_link",
            candidate_id=cand.id,
            roles=[role] if role else [],
        )
        db.add(user)
        db.flush()
    return issue_tokens(db, user)


# --- OpenID Connect ------------------------------------------------------------------
_discovery_cache: dict[str, dict[str, Any]] = {}


def _discovery() -> dict[str, Any]:
    s = get_settings()
    if not s.oidc_issuer:
        raise AuthenticationError("SSO is not configured")
    if s.oidc_issuer not in _discovery_cache:
        try:
            r = httpx.get(s.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("OIDC discovery failed") from exc
        _discovery_cache[s.oidc_issuer] = r.json()
    return _discovery_cache[s.oidc_issuer]


def oidc_authorize_url(state: str, nonce: str) -> str:
    s = get_settings()
    d = _discovery()
    return (
        d["authorization_endpoint"]
        + "?"
        + urlencode(
            {
                "client_id": s.oidc_client_id,
                "response_type": "code",
                "scope": "openid email profile",
                "redirect_uri": s.oidc_redirect_uri,
                "state": state,
                "nonce": nonce,
            }
        )
    )


def oidc_callback(db: Session, code: str, nonce: str) -> dict:
    s = get_settings()
    d = _discovery()
    try:
        r = httpx.post(
            d["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": s.oidc_redirect_uri,
                "client_id": s.oidc_client_id,
                "client_secret": s.oidc_client_secret.get_secret_value() if s.oidc_client_secret else None,
            },
            timeout=15,
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise ExternalServiceError("OIDC token exchange failed") from exc
    id_token = r.json().get("id_token")
    if not id_token:
        raise AuthenticationError("No id_token returned")
    jwks = jwt.PyJWKClient(d["jwks_uri"])
    key = jwks.get_signing_key_from_jwt(id_token).key
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=s.oidc_client_id,
            issuer=d.get("issuer", s.oidc_issuer),
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid id_token") from exc
    if claims.get("nonce") != nonce:
        raise AuthenticationError("Invalid nonce")
    email = (claims.get("email") or "").lower()
    if not email or claims.get("email_verified") is False:
        raise AuthenticationError("Verified e-mail required")
    user = db.scalar(select(User).where((User.external_subject == claims["sub"]) | (func.lower(User.email) == email)))
    if not user:
        # Just-in-time provisioning is limited to the configured default org with the least-privilege role.
        org = (
            db.scalar(select(Organization).where(Organization.slug == s.oidc_default_org_slug))
            if s.oidc_default_org_slug
            else None
        )
        if not org:
            raise AuthenticationError("No account for this identity; ask your administrator for access")
        role = db.scalar(
            select(RoleDef).where(RoleDef.key == Role.INTERVIEWER.value, RoleDef.organization_id.is_(None))
        )
        user = User(
            organization_id=org.id,
            email=email,
            full_name=claims.get("name") or email,
            auth_provider="oidc",
            external_subject=claims["sub"],
            password_hash=None,
            roles=[role] if role else [],
        )
        db.add(user)
        db.flush()
    elif not user.external_subject:
        user.external_subject = claims["sub"]
    if not user.is_active:
        raise AuthenticationError("User inactive")
    user.last_login_at = _now()
    return issue_tokens(db, user)


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
