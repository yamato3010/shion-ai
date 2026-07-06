"""Agent Engine: 1メッセージの応答オーケストレーション(docs/02 §5.1)

フェーズ0の範囲: 履歴ロード → プロンプト組立 → ストリーミング生成 → 感情タグ抽出 → 永続化。
ツール実行・長期記憶はフェーズ1/2で追加する。
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.core.persona import EmotionTagParser, Persona
from shion.db.models import Conversation, Message
from shion.llm import LLMRouter
from shion.llm import Message as LLMMessage

logger = logging.getLogger(__name__)


class AgentEngine:
    def __init__(
        self,
        router: LLMRouter,
        persona: Persona,
        session_factory: async_sessionmaker,
        history_limit: int = 30,
    ) -> None:
        self._router = router
        self._persona = persona
        self._sessions = session_factory
        self._history_limit = history_limit

    async def stream_reply(
        self,
        conversation_id: int | None,
        text: str,
        interface: str = "web",
    ) -> AsyncIterator[dict]:
        """応答をイベント列(docs/05 §1.4 のWSメッセージ形式)として返す"""
        async with self._sessions() as db:
            conversation, created = await self._get_or_create_conversation(db, conversation_id, text)
            if created:
                yield {"type": "session", "conversation_id": conversation.id, "title": conversation.title}

            db.add(Message(conversation_id=conversation.id, role="user", content=text, interface=interface))
            await db.commit()
            history = await self._load_history(db, conversation.id)

        messages = [LLMMessage(role="system", content=self._persona.build_system_prompt()), *history]

        parser = EmotionTagParser(self._persona.emotions)
        reply_parts: list[str] = []
        try:
            async for chunk in self._router.stream(messages, purpose="chat"):
                if not chunk.text:
                    continue
                out, emotion = parser.feed(chunk.text)
                if emotion:
                    yield {"type": "emotion", "value": emotion}
                if out:
                    reply_parts.append(out)
                    yield {"type": "chunk", "text": out}
        except Exception as e:  # noqa: BLE001 - 失敗はイベントとしてクライアントへ返す
            logger.exception("応答生成に失敗")
            yield {"type": "error", "message": str(e)}
            return

        tail = parser.flush()
        if tail:
            reply_parts.append(tail)
            yield {"type": "chunk", "text": tail}

        reply = "".join(reply_parts)
        emotion = parser.emotion or "normal"
        async with self._sessions() as db:
            msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=reply,
                emotion=emotion,
                interface=interface,
            )
            db.add(msg)
            await db.commit()
            message_id = msg.id

        yield {
            "type": "done",
            "conversation_id": conversation.id,
            "message_id": message_id,
            "emotion": emotion,
        }

    async def _get_or_create_conversation(
        self, db, conversation_id: int | None, first_text: str
    ) -> tuple[Conversation, bool]:
        if conversation_id is not None:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is not None:
                return conversation, False
        title = first_text.replace("\n", " ").strip()[:30] or "新しい会話"
        conversation = Conversation(title=title)
        db.add(conversation)
        await db.commit()
        return conversation, True

    async def _load_history(self, db, conversation_id: int) -> list[LLMMessage]:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(self._history_limit)
            )
        ).scalars().all()
        return [LLMMessage(role=m.role, content=m.content) for m in reversed(rows)]
