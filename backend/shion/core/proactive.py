"""プロアクティブ会話(docs/09 フェーズ4)

プラグインが `self.speak(指示文)` で speak.request イベントを発行すると、
ここが Agent Engine で人格込みの発話を生成し、会話に保存した上で
Web(WSブロードキャスト)と Discord(オーナーDM)へ届ける。
プラグインはLLMや配信先を知らなくてよい。
"""

from __future__ import annotations

import logging

from shion.core.events import EventBus

logger = logging.getLogger(__name__)

EVENT_SPEAK = "speak.request"


class ProactiveSpeaker:
    def __init__(self, events: EventBus, agent, ws_manager) -> None:
        self._agent = agent
        self._ws_manager = ws_manager
        self._discord = None
        events.subscribe(EVENT_SPEAK, self.handle)

    def set_discord(self, adapter) -> None:
        self._discord = adapter

    async def handle(self, payload: dict) -> None:
        instruction = (payload.get("instruction") or "").strip()
        if not instruction:
            return
        try:
            result = await self._agent.proactive_reply(instruction)
        except Exception:  # noqa: BLE001 - 発話失敗でイベント処理を止めない
            logger.exception("プロアクティブ発話の生成に失敗(plugin=%s)", payload.get("plugin"))
            return
        if result is None:
            return

        logger.info("プロアクティブ発話: %s", result["text"][:60])
        await self._ws_manager.broadcast({"type": "proactive", **result})

        if self._discord is not None:
            try:
                await self._discord.send_proactive(result["text"], result["emotion"])
            except Exception:  # noqa: BLE001
                logger.exception("プロアクティブ発話のDiscord配信に失敗")
