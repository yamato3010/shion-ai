from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from shion.db.models import Base


def make_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    # フェーズ0はcreate_allで運用。スキーマ変更が始まったらAlembic導入(docs/02)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
