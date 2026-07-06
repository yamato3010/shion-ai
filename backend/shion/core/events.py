"""プロセス内 Event Bus(docs/02 §5.2)

プラグインとコアはここを介して疎結合に通信する。
主要イベント: notification.send(通知配送)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def subscribe(self, event: str, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        handlers = self._handlers.get(event) or []
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: str, payload: dict) -> None:
        """全購読者を並行実行。ハンドラの例外は発行側へ伝播させない(障害隔離)"""
        handlers = list(self._handlers.get(event) or [])
        if not handlers:
            logger.debug("イベント %s に購読者がいません", event)
            return
        results = await asyncio.gather(
            *(h(payload) for h in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.error("イベント %s のハンドラ %s が失敗: %s", event, handler, result)
