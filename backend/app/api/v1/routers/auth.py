from __future__ import annotations

import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import DB, CurrentPrincipal, client_ip
from app.core.errors import AuthenticationError
from app.models.org import Organization, User
from app.schemas.common import Message
from app.schemas.org import LoginIn, MeOut, RefreshIn, TokenOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenOut, summary="Password login (rate limited, lockout after 5 failures)")
def login(data: LoginIn, request: Request, db: DB) -> dict:
    tokens = auth_service.login(
        db, data.email, data.password, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenOut, summary="Rotate refresh token")
def refresh(data: RefreshIn, request: Request, db: DB) -> dict:
    tokens = auth_service.refresh(db, data.refresh_token, user_agent=request.headers.get("user-agent"))
    db.commit()
    return tokens


@router.post("/logout", response_model=Message)
def logout(data: RefreshIn, db: DB) -> Message:
    auth_service.logout(db, data.refresh_token)
    db.commit()
    return Message(message="Logged out")


@router.get("/me", response_model=MeOut)
def me(p: CurrentPrincipal, db: DB) -> MeOut:
    user = db.get(User, p.user_id)
    assert user
    org = db.get(Organization, p.organization_id)
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org.id if org else None,
        organization_name=org.name if org else None,
        roles=list(p.roles),
        permissions=sorted(p.permissions),
    )


@router.post("/candidate/verify", response_model=TokenOut, summary="Exchange a candidate portal magic link token")
def candidate_verify(data: RefreshIn, db: DB) -> dict:
    tokens = auth_service.exchange_candidate_magic_token(db, data.refresh_token)
    db.commit()
    return tokens


@router.get("/oidc/login", summary="Start OpenID Connect SSO", response_class=RedirectResponse)
def oidc_login() -> Response:
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    resp = RedirectResponse(auth_service.oidc_authorize_url(state, nonce), status_code=302)
    for k, v in (("oidc_state", state), ("oidc_nonce", nonce)):
        resp.set_cookie(k, v, max_age=600, httponly=True, secure=True, samesite="lax")
    return resp


@router.get("/oidc/callback", response_model=TokenOut, summary="OpenID Connect callback")
def oidc_callback(code: str, state: str, request: Request, db: DB) -> dict:
    if not secrets.compare_digest(state, request.cookies.get("oidc_state", "")):
        raise AuthenticationError("Invalid state")
    tokens = auth_service.oidc_callback(db, code, request.cookies.get("oidc_nonce", ""))
    db.commit()
    return tokens
