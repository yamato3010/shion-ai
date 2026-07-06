"""通知ルーティング(docs/03 §4)

プラグインは論理チャネル(daily / important / default)へ通知を発行し、
実際の配送先は config.yaml の notifications.routes で決まる。
配送先: web(WebSocketプッシュ)/ discord_dm(オーナーへのDM。Bot稼働時のみ)。
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
        self._discord = None  # DiscordAdapter(Bot起動時に set_discord で注入)
        events.subscribe(EVENT_NOTIFICATION, self.handle)

    def set_discord(self, adapter) -> None:
        self._discord = adapter

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
            elif target == "discord_dm":
                if self._discord is None:
                    logger.debug("Discord Bot未稼働のため discord_dm への通知をスキップ")
                    continue
                try:
                    await self._discord.send_notification(payload)
                except Exception:  # noqa: BLE001 - 通知失敗でイベント処理を止めない
                    logger.exception("Discord DM通知の送信に失敗")
            else:
                logger.warning("通知先 '%s' は未実装のためスキップ(channel=%s)", target, channel)
