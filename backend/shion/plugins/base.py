"""プラグイン基底クラスとデコレータ(docs/03_plugin_system.md)

プラグインは PluginBase を継承し、@tool / @job / @command で能力を宣言する。
コアへのアクセスは PluginBase のプロパティ経由に限定される。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.core.events import EventBus
from shion.core.notifications import EVENT_NOTIFICATION
from shion.db.models import PluginKV
from shion.llm import LLMRouter
from shion.llm import Message as LLMMessage

ATTR_TOOL = "_shion_tool"
ATTR_JOB = "_shion_job"
ATTR_COMMAND = "_shion_command"


def tool(description: str | None = None, requires_confirmation: bool = False) -> Callable:
    """LLMのfunction callingから呼び出せるツールとして登録する"""

    def decorator(fn: Callable) -> Callable:
        setattr(
            fn,
            ATTR_TOOL,
            {
                "description": description or (fn.__doc__ or "").strip(),
                "requires_confirmation": requires_confirmation,
            },
        )
        return fn

    return decorator


def job(cron: str | Callable[[Any], str]) -> Callable:
    """定期実行ジョブとして登録する。

    cron: 5フィールドのcron式。設定値から動的に決める場合は
          `lambda self: daily_cron(self.config["notify_time"])` のように callable を渡す。
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, ATTR_JOB, {"cron": cron})
        return fn

    return decorator


def command(name: str | None = None, description: str = "") -> Callable:
    """インターフェース固有コマンド(Discordスラッシュコマンド等)。

    フェーズ2のDiscordアダプタ実装時に配線される。宣言だけ先に可能。
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, ATTR_COMMAND, {"name": name or fn.__name__, "description": description})
        return fn

    return decorator


def daily_cron(hhmm: str) -> str:
    """"07:30" のような時刻表記を毎日実行のcron式に変換するヘルパ"""
    hour, _, minute = hhmm.partition(":")
    return f"{int(minute or 0)} {int(hour)} * * *"


class PluginStorage:
    """プラグイン専用のkey-value永続化(SQLiteの名前空間付き領域)"""

    def __init__(self, session_factory: async_sessionmaker, plugin_name: str) -> None:
        self._sessions = session_factory
        self._plugin = plugin_name

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._sessions() as db:
            row = (
                await db.execute(
                    select(PluginKV).where(
                        PluginKV.plugin_name == self._plugin, PluginKV.key == key
                    )
                )
            ).scalar_one_or_none()
        return json.loads(row.value_json) if row else default

    async def set(self, key: str, value: Any) -> None:
        async with self._sessions() as db:
            row = (
                await db.execute(
                    select(PluginKV).where(
                        PluginKV.plugin_name == self._plugin, PluginKV.key == key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = PluginKV(plugin_name=self._plugin, key=key, value_json=json.dumps(value))
                db.add(row)
            else:
                row.value_json = json.dumps(value)
            await db.commit()

    async def delete(self, key: str) -> None:
        async with self._sessions() as db:
            await db.execute(
                delete(PluginKV).where(PluginKV.plugin_name == self._plugin, PluginKV.key == key)
            )
            await db.commit()


class _MissingOAuthStore:
    """oauth store 未注入時のプレースホルダ。使おうとした時点で分かりやすく失敗させる"""

    def __getattr__(self, name: str):
        if name in ("save", "load", "delete"):  # 実際に使おうとした時だけ明確に失敗させる
            raise RuntimeError("OAuthトークンストアが利用できません(コアの初期化を確認)")
        raise AttributeError(name)  # inspect等の内省は通常のAttributeErrorで素通し


@dataclass
class PluginContext:
    name: str
    config: dict = field(default_factory=dict)
    llm: LLMRouter | None = None
    events: EventBus | None = None
    storage: PluginStorage | None = None
    oauth: Any = None  # OAuthTokenStore(外部サービス連携プラグイン用)


class PluginBase:
    def __init__(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self.logger = logging.getLogger(f"shion.plugin.{ctx.name}")

    # --- コアAPI(docs/03 §2.3) ---

    @property
    def name(self) -> str:
        return self._ctx.name

    @property
    def config(self) -> dict:
        return self._ctx.config

    @property
    def events(self) -> EventBus:
        assert self._ctx.events is not None
        return self._ctx.events

    @property
    def storage(self) -> PluginStorage:
        assert self._ctx.storage is not None
        return self._ctx.storage

    @property
    def llm(self) -> LLMRouter:
        assert self._ctx.llm is not None
        return self._ctx.llm

    @property
    def oauth(self):
        """OAuthトークンストア(save/load/delete)。連携はWeb UIのOAuthフローで行う。

        注: assert ではなく遅延エラーにする(inspect.getmembers がプロパティを
        評価するため、未注入でもプロパティ参照自体は失敗させない)
        """
        return self._ctx.oauth if self._ctx.oauth is not None else _MissingOAuthStore()

    async def notify(
        self,
        title: str,
        body: str,
        channel: str = "default",
        url: str | None = None,
    ) -> None:
        """ユーザーへの通知。配送先(web/discord)はコアのルーティング設定が決める"""
        await self.events.publish(
            EVENT_NOTIFICATION,
            {"title": title, "body": body, "channel": channel, "url": url, "plugin": self.name},
        )

    async def llm_text(self, prompt: str, purpose: str = "summarize") -> str:
        """LLMで単発のテキスト生成をする便利メソッド(使用量はコアで一元管理)"""
        parts: list[str] = []
        async for chunk in self.llm.stream([LLMMessage(role="user", content=prompt)], purpose=purpose):
            if chunk.text:
                parts.append(chunk.text)
        return "".join(parts)

    # --- ライフサイクルフック ---

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    # --- ダッシュボード(📊)への表示。任意でオーバーライドする ---

    async def dashboard(self) -> dict | None:
        """📊ダッシュボードに出すカードを返す。表示しないなら None(既定)。

        形式: {"title": str, "items": [{"text": str, "url": str | None}], "footer": str | None}
        """
        return None
