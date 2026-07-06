"""パスワード認証 + 署名Cookieセッション(docs/08_security.md §2)"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from itsdangerous import BadSignature, TimestampSigner
from pydantic import BaseModel

COOKIE_NAME = "shion_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30日

router = APIRouter()


def _issue_token(secret_key: str) -> str:
    return TimestampSigner(secret_key).sign("ok").decode()


def _verify_token(token: str | None, secret_key: str) -> bool:
    if not token:
        return False
    try:
        value = TimestampSigner(secret_key).unsign(token, max_age=SESSION_MAX_AGE)
        return value == b"ok"
    except BadSignature:
        return False


def is_authenticated(cookies: dict, secret_key: str) -> bool:
    return _verify_token(cookies.get(COOKIE_NAME), secret_key)


def require_auth(request: Request) -> None:
    if not is_authenticated(request.cookies, request.app.state.settings.secret_key):
        raise HTTPException(status_code=401, detail="ログインが必要です")


class LoginBody(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    settings = request.app.state.settings
    if not hmac.compare_digest(body.password, settings.password):
        raise HTTPException(status_code=401, detail="パスワードが違います")
    response.set_cookie(
        COOKIE_NAME,
        _issue_token(settings.secret_key),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    authed = is_authenticated(request.cookies, request.app.state.settings.secret_key)
    return {"authenticated": authed, "assistant_name": request.app.state.persona.name}
