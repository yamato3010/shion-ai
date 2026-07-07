"""エントリポイント。

    cd backend && uvicorn shion.main:app --reload --port 8000

FastAPI(REST + WebSocket)+ Discord Bot + Scheduler + プラグイン基盤を
単一 asyncio イベントループに同居させる(docs/02 §7)。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from shion.config import Settings
from shion.core.agent import AgentEngine
from shion.core.events import EventBus
from shion.core.memory import MemoryManager
from shion.core.notifications import NotificationRouter
from shion.core.oauth_store import OAuthTokenStore
from shion.core.persona import Persona
from shion.core.scheduler import Scheduler
from shion.core.usage import UsageRecorder
from shion.db.session import init_db, make_engine, make_session_factory
from shion.interfaces.web import (
    auth,
    conversations,
    dashboard,
    google_oauth,
    memories,
    plugins,
    ws,
)
from shion.interfaces.web.ws_manager import WSManager
from shion.llm import LLMRouter
from shion.plugins import PluginManager

logger = logging.getLogger(__name__)

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
        usage_recorder = UsageRecorder(sessions, settings.llm.get("pricing"))
        llm_router.set_usage_recorder(usage_recorder)
        oauth_store = OAuthTokenStore(sessions, settings.secret_key)
        plugin_manager = PluginManager(
            plugins_dir=settings.root / "plugins",
            session_factory=sessions,
            llm=llm_router,
            events=events,
            scheduler=scheduler,
            oauth_store=oauth_store,
        )

        app.state.settings = settings
        app.state.sessions = sessions
        app.state.events = events
        app.state.ws_manager = ws_manager
        app.state.scheduler = scheduler
        app.state.llm_router = llm_router
        app.state.usage_recorder = usage_recorder
        app.state.oauth_store = oauth_store
        app.state.plugin_manager = plugin_manager
        memory = MemoryManager(sessions, llm_router)
        app.state.memory = memory
        app.state.persona = Persona.load(settings.root / "config" / "persona.yaml")
        app.state.agent = AgentEngine(
            router=llm_router,
            persona=app.state.persona,
            session_factory=sessions,
            plugin_manager=plugin_manager,
            memory=memory,
            history_limit=int(settings.chat.get("history_limit", 30)),
        )

        # 通知ルーティング(notification.send → web / discord_dm へ配送)
        notification_router = NotificationRouter(
            events,
            (settings.config.get("notifications") or {}).get("routes"),
            ws_manager,
        )

        await plugin_manager.setup()
        scheduler.start()

        # Discord Bot(DISCORD_BOT_TOKEN 設定時のみ起動)
        discord_adapter = None
        discord_task: asyncio.Task | None = None
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if token:
            from shion.interfaces.discord.adapter import DiscordAdapter

            discord_adapter = DiscordAdapter(
                agent=app.state.agent,
                plugin_manager=plugin_manager,
                llm_router=llm_router,
                memory=memory,
                session_factory=sessions,
                config=settings.config.get("discord") or {},
            )
            notification_router.set_discord(discord_adapter)
            discord_task = asyncio.create_task(discord_adapter.run_forever(token))
        else:
            logger.info("DISCORD_BOT_TOKEN 未設定のため Discord Bot は起動しません")

        yield

        if discord_adapter is not None:
            await discord_adapter.close()
        if discord_task is not None:
            discord_task.cancel()
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
    app.include_router(
        memories.router,
        prefix="/api",
        tags=["memories"],
        dependencies=[Depends(auth.require_auth)],
    )
    app.include_router(
        dashboard.router,
        prefix="/api",
        tags=["dashboard"],
        dependencies=[Depends(auth.require_auth)],
    )
    app.include_router(
        google_oauth.router,
        prefix="/api",
        tags=["google"],
        dependencies=[Depends(auth.require_auth)],
    )
    app.include_router(ws.router, prefix="/api")

    # 本番: ビルド済みフロントエンドを配信(開発時は Vite dev server を使う)
    dist = settings.root / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
