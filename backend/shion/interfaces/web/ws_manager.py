"""WebSocket接続管理。

チャット応答と通知プッシュが同一ソケットに同居するため、
接続ごとのロックで送信順序を保証する。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, asyncio.Lock] = {}

    def register(self, ws: WebSocket) -> None:
        self._connections[ws] = asyncio.Lock()

    def unregister(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    async def send(self, ws: WebSocket, data: dict) -> None:
        lock = self._connections.get(ws)
        if lock is None:
            return
        async with lock:
            await ws.send_json(data)

    async def broadcast(self, data: dict) -> None:
        for ws in list(self._connections.keys()):
            try:
                await self.send(ws, data)
            except Exception:  # noqa: BLE001 - 切断済みソケットは握りつぶして除去
                self.unregister(ws)
