"""エントリポイント。

    cd backend && uvicorn shion.main:app --reload --port 8000

フェーズ0: FastAPI(REST + WebSocket)のみ。
Discord Bot / Scheduler はフェーズ1以降でここに同居させる(docs/02 §7)。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from shion.config import Settings
from shion.core.agent import AgentEngine
from shion.core.persona import Persona
from shion.db.session import init_db, make_engine, make_session_factory
from shion.interfaces.web import auth, conversations, ws
from shion.llm import LLMRouter

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.db_url)
        await init_db(engine)

        app.state.settings = settings
        app.state.sessions = make_session_factory(engine)
        app.state.persona = Persona.load(settings.root / "config" / "persona.yaml")
        app.state.llm_router = LLMRouter(settings.llm)
        app.state.agent = AgentEngine(
            router=app.state.llm_router,
            persona=app.state.persona,
            session_factory=app.state.sessions,
            history_limit=int(settings.chat.get("history_limit", 30)),
        )
        yield
        await app.state.llm_router.close()
        await engine.dispose()

    app = FastAPI(title="shion-ai", lifespan=lifespan)
    app.state.settings = settings  # lifespan前(認証ミドルウェア等)でも参照可能に

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(
        conversations.router,
        prefix="/api",
        tags=["conversations"],
        dependencies=[Depends(auth.require_auth)],
    )
    app.include_router(ws.router, prefix="/api")

    # 本番: ビルド済みフロントエンドを配信(開発時は Vite dev server を使う)
    dist = settings.root / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
