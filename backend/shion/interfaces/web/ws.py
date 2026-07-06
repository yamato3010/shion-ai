"""チャット用 WebSocket(docs/05 §1.4)

クライアント → サーバ: {"type": "chat", "conversation_id": int | null, "text": str}
サーバ → クライアント: session / emotion / chunk / done / error イベント
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shion.interfaces.web.auth import is_authenticated

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def chat_ws(websocket: WebSocket):
    settings = websocket.app.state.settings
    if not is_authenticated(websocket.cookies, settings.secret_key):
        await websocket.close(code=4401, reason="unauthorized")
        return

    await websocket.accept()
    agent = websocket.app.state.agent
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "chat":
                continue
            text = (data.get("text") or "").strip()
            if not text:
                continue
            async for event in agent.stream_reply(
                conversation_id=data.get("conversation_id"),
                text=text,
                interface="web",
            ):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("WebSocketハンドラで予期しないエラー")
        await websocket.close(code=1011)
