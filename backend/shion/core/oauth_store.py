"""OAuthトークンの暗号化保存(docs/06 §2, docs/08)

SHION_SECRET_KEY から導出した鍵(Fernet)で access/refresh トークンを暗号化して
oauth_tokens テーブルに保存する。Google固有のリフレッシュ処理は各プラグイン側の責務。
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.db.models import OAuthToken


def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


class OAuthTokenStore:
    def __init__(self, session_factory: async_sessionmaker, secret_key: str) -> None:
        self._sessions = session_factory
        self._fernet = _fernet(secret_key)

    async def save(
        self,
        provider: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        scopes: str = "",
    ) -> None:
        async with self._sessions() as db:
            row = await db.get(OAuthToken, provider)
            if row is None:
                row = OAuthToken(provider=provider, access_token_enc="")
                db.add(row)
            row.access_token_enc = self._fernet.encrypt(access_token.encode()).decode()
            if refresh_token:  # 再認可時にrefresh_tokenが返らないことがあるため上書きは値があるときのみ
                row.refresh_token_enc = self._fernet.encrypt(refresh_token.encode()).decode()
            row.expires_at = expires_at
            if scopes:
                row.scopes = scopes
            await db.commit()

    async def load(self, provider: str) -> dict | None:
        """{access_token, refresh_token, expires_at, scopes} を返す。未連携なら None"""
        async with self._sessions() as db:
            row = await db.get(OAuthToken, provider)
        if row is None:
            return None
        try:
            access = self._fernet.decrypt(row.access_token_enc.encode()).decode()
            refresh = (
                self._fernet.decrypt(row.refresh_token_enc.encode()).decode()
                if row.refresh_token_enc
                else None
            )
        except InvalidToken:
            # SHION_SECRET_KEY が変わった等で復号できない → 再連携が必要
            return None
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": row.expires_at,
            "scopes": row.scopes,
        }

    async def delete(self, provider: str) -> None:
        async with self._sessions() as db:
            await db.execute(delete(OAuthToken).where(OAuthToken.provider == provider))
            await db.commit()
