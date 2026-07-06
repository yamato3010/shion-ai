"""通知ルーティング(docs/03 §4)

プラグインは論理チャネル(daily / important / default)へ通知を発行し、
実際の配送先は config.yaml の notifications.routes で決まる。
フェーズ1の配送先は web(WebSocketプッシュ)のみ。discord はフェーズ2で追加。
"""

from __future__ import annotations

import logging

from shion.core.events import EventBus

logger = logging.getLogger(__name__)

EVENT_NOTIFICATION = "notification.send"


class NotificationRouter:
    def __init__(self, events: EventBus, routes: dict | None, ws_manager) -> None:
        self._routes = routes or {}
        self._ws_manager = ws_manager
        events.subscribe(EVENT_NOTIFICATION, self.handle)

    async def handle(self, payload: dict) -> None:
        channel = payload.get("channel", "default")
        targets = self._routes.get(channel) or self._routes.get("default") or ["web"]
        for target in targets:
            if target == "web":
                await self._ws_manager.broadcast(
                    {
                        "type": "notification",
                        "title": payload.get("title", ""),
                        "body": payload.get("body", ""),
                        "channel": channel,
                        "url": payload.get("url"),
                    }
                )
            else:
                # discord 等はフェーズ2でアダプタを追加する
                logger.warning("通知先 '%s' は未実装のためスキップ(channel=%s)", target, channel)
