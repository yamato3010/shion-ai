"""エントリポイント。

    cd backend && uvicorn shion.main:app --reload --port 8000

FastAPI(REST + WebSocket)+ Scheduler + プラグイン基盤。
Discord Bot はフェーズ2でここに同居させる(docs/02 §7)。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from shion.config import Settings
from shion.core.agent import AgentEngine
from shion.core.events import EventBus
from shion.core.notifications import NotificationRouter
from shion.core.persona import Persona
from shion.core.scheduler import Scheduler
from shion.db.session import init_db, make_engine, make_session_factory
from shion.interfaces.web import auth, conversations, plugins, ws
from shion.interfaces.web.ws_manager import WSManager
from shion.llm import LLMRouter
from shion.plugins import PluginManager

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.db_url)
        await init_db(engine)

        sessions = make_session_factory(engine)
        events = EventBus()
        ws_manager = WSManager()
        scheduler = Scheduler(sessions)
        llm_router = LLMRouter(settings.llm)
        plugin_manager = PluginManager(
            plugins_dir=settings.root / "plugins",
            session_factory=sessions,
            llm=llm_router,
            events=events,
            scheduler=scheduler,
        )

        app.state.settings = settings
        app.state.sessions = sessions
        app.state.events = events
        app.state.ws_manager = ws_manager
        app.state.scheduler = scheduler
        app.state.llm_router = llm_router
        app.state.plugin_manager = plugin_manager
        app.state.persona = Persona.load(settings.root / "config" / "persona.yaml")
        app.state.agent = AgentEngine(
            router=llm_router,
            persona=app.state.persona,
            session_factory=sessions,
            plugin_manager=plugin_manager,
            history_limit=int(settings.chat.get("history_limit", 30)),
        )

        # 通知ルーティング(notification.send → web へ配送)
        NotificationRouter(
            events,
            (settings.config.get("notifications") or {}).get("routes"),
            ws_manager,
        )

        await plugin_manager.setup()
        scheduler.start()
        yield
        scheduler.shutdown()
        await llm_router.close()
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
    app.include_router(
        plugins.router,
        prefix="/api",
        tags=["plugins"],
        dependencies=[Depends(auth.require_auth)],
    )
    app.include_router(ws.router, prefix="/api")

    # 本番: ビルド済みフロントエンドを配信(開発時は Vite dev server を使う)
    dist = settings.root / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
