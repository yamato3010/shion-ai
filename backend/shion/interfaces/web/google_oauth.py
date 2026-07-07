"""Google OAuth 2.0 フロー(docs/06 §2)

- GET /api/google/status    連携状態
- GET /api/google/oauth/start     認可URLへリダイレクト
- GET /api/google/oauth/callback  コード受領 → トークン交換 → 暗号化保存
- POST /api/google/disconnect     連携解除

クライアントID/シークレットは .env の GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET。
トークンは google_workspace プラグインが oauth ストア経由で利用する。
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, TimestampSigner

logger = logging.getLogger(__name__)

router = APIRouter()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
PROVIDER = "google"


def _client_creds() -> tuple[str, str]:
    return os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/google/oauth/callback"


@router.get("/google/status")
async def google_status(request: Request):
    client_id, _ = _client_creds()
    token = await request.app.state.oauth_store.load(PROVIDER)
    return {"configured": bool(client_id), "connected": token is not None}


@router.get("/google/oauth/start")
async def oauth_start(request: Request):
    client_id, client_secret = _client_creds()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が .env に未設定です",
        )
    # CSRF対策: stateを署名して発行し、コールバックで検証する
    signer = TimestampSigner(request.app.state.settings.secret_key)
    state = signer.sign(secrets.token_urlsafe(16).encode()).decode()
    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # refresh_token を得る
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")


@router.get("/google/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"<p>Google連携がキャンセルされました: {error}</p><a href='/'>戻る</a>")
    signer = TimestampSigner(request.app.state.settings.secret_key)
    try:
        signer.unsign(state, max_age=600)
    except BadSignature:
        raise HTTPException(status_code=400, detail="stateの検証に失敗しました(再度お試しください)")

    client_id, client_secret = _client_creds()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        logger.error("Googleトークン交換に失敗: %s", resp.text[:300])
        raise HTTPException(status_code=502, detail="Googleトークン交換に失敗しました")

    data = resp.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
    await request.app.state.oauth_store.save(
        PROVIDER,
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=data.get("scope", ""),
    )
    logger.info("Google連携が完了しました")
    return RedirectResponse("/")


@router.post("/google/disconnect")
async def disconnect(request: Request):
    await request.app.state.oauth_store.delete(PROVIDER)
    return {"ok": True}
