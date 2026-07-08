"""Agent Engine: 1メッセージの応答オーケストレーション(docs/02 §5.1)

履歴ロード → 長期記憶検索 → プロンプト組立 → 生成 →(ツール実行 → 再生成)ループ
→ 感情タグ抽出 → 永続化 → 記憶抽出(非同期)。
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.core.memory import MemoryManager, spawn_extraction
from shion.core.persona import EmotionTagParser, Persona
from shion.db.models import Conversation, Message
from shion.llm import LLMRouter
from shion.llm import Message as LLMMessage

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


class AgentEngine:
    def __init__(
        self,
        router: LLMRouter,
        persona: Persona,
        session_factory: async_sessionmaker,
        plugin_manager=None,
        memory: MemoryManager | None = None,
        events=None,
        history_limit: int = 30,
    ) -> None:
        self._router = router
        self._persona = persona
        self._sessions = session_factory
        self._plugins = plugin_manager
        self._memory = memory
        self._events = events  # EventBus(message.received / message.responded を発行)
        self._history_limit = history_limit
        self._bg_tasks: set = set()  # 記憶抽出タスクのGC防止

    async def _publish(self, event: str, payload: dict) -> None:
        if self._events is not None:
            await self._events.publish(event, payload)

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

        await self._publish(
            "message.received",
            {"conversation_id": conversation.id, "interface": interface},
        )

        system_prompt = self._persona.build_system_prompt()
        if self._memory:
            try:
                memories = await self._memory.search(text, k=5)
                if memories:
                    system_prompt += "\n\n" + self._memory.format_for_prompt(memories)
            except Exception:  # noqa: BLE001 - 記憶検索の失敗で会話を止めない
                logger.exception("長期記憶の検索に失敗")

        messages = [LLMMessage(role="system", content=system_prompt), *history]
        toolspecs = self._plugins.get_toolspecs() if self._plugins else []

        reply_parts: list[str] = []
        final_emotion: str | None = None

        for _round in range(MAX_TOOL_ROUNDS):
            # 感情タグは各生成ラウンドの冒頭に付くため、ラウンドごとにパースする
            parser = EmotionTagParser(self._persona.emotions)
            round_parts: list[str] = []
            tool_calls: list[dict] = []
            try:
                async for chunk in self._router.stream(
                    messages, purpose="chat", tools=toolspecs or None
                ):
                    if chunk.text:
                        out, emotion = parser.feed(chunk.text)
                        if emotion:
                            final_emotion = emotion
                            yield {"type": "emotion", "value": emotion}
                        if out:
                            round_parts.append(out)
                            yield {"type": "chunk", "text": out}
                    if chunk.tool_call and chunk.tool_call.get("name"):
                        tool_calls.append(chunk.tool_call)
            except Exception as e:  # noqa: BLE001 - 失敗はイベントとしてクライアントへ返す
                logger.exception("応答生成に失敗")
                yield {"type": "error", "message": str(e)}
                return

            tail = parser.flush()
            if tail:
                round_parts.append(tail)
                yield {"type": "chunk", "text": tail}
            reply_parts.extend(round_parts)

            if not tool_calls:
                break

            # ツール実行 → 結果をコンテキストに積んで再生成
            messages.append(
                LLMMessage(
                    role="assistant",
                    content="".join(round_parts),
                    tool_calls=[
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
                            # Gemini 3 の thought_signature 等、プロバイダ固有フィールドを往復させる
                            **({"extra_content": tc["extra_content"]} if tc.get("extra_content") else {}),
                        }
                        for tc in tool_calls
                    ],
                )
            )
            for tc in tool_calls:
                yield {"type": "tool_status", "name": tc["name"], "state": "running"}
                state, result_text = await self._run_tool(tc)
                yield {"type": "tool_status", "name": tc["name"], "state": state}
                messages.append(
                    LLMMessage(role="tool", content=result_text, tool_call_id=tc["id"])
                )
        else:
            logger.warning("ツール実行が%d回続いたため打ち切り", MAX_TOOL_ROUNDS)

        reply = "".join(reply_parts)
        emotion = final_emotion or "normal"
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

        if self._memory and reply:
            spawn_extraction(self._memory, text, reply, self._bg_tasks)

        await self._publish(
            "message.responded",
            {"conversation_id": conversation.id, "interface": interface},
        )

        yield {
            "type": "done",
            "conversation_id": conversation.id,
            "message_id": message_id,
            "emotion": emotion,
        }

    async def proactive_reply(self, instruction: str) -> dict | None:
        """プラグイン起点の自発的発話(docs/09 フェーズ4)。

        指示文はプロンプトにのみ使い、会話履歴には保存しない。生成結果は
        最新の会話に assistant メッセージとして保存する(会話が無ければ新規作成)。
        戻り値: {conversation_id, message_id, text, emotion} / 生成できなければ None
        """
        async with self._sessions() as db:
            conversation = (
                await db.execute(select(Conversation).order_by(Conversation.id.desc()).limit(1))
            ).scalar_one_or_none()
            if conversation is None:
                conversation = Conversation(title="紫桜より")
                db.add(conversation)
                await db.commit()
            history = await self._load_history(db, conversation.id)

        system_prompt = self._persona.build_system_prompt()
        if self._memory:
            try:
                memories = await self._memory.search(instruction, k=3)
                if memories:
                    system_prompt += "\n\n" + self._memory.format_for_prompt(memories)
            except Exception:  # noqa: BLE001
                logger.exception("長期記憶の検索に失敗")

        messages = [
            LLMMessage(role="system", content=system_prompt),
            *history,
            LLMMessage(
                role="user",
                content=(
                    "(これはシステムからの演出指示で、ユーザーの発言ではない。"
                    "指示文自体には言及せず、あなたから自然に話しかけること)\n"
                    f"指示: {instruction}\n短く1〜3文で。"
                ),
            ),
        ]

        parser = EmotionTagParser(self._persona.emotions)
        parts: list[str] = []
        emotion: str | None = None
        async for chunk in self._router.stream(messages, purpose="chat"):
            if chunk.text:
                out, resolved = parser.feed(chunk.text)
                if resolved:
                    emotion = resolved
                if out:
                    parts.append(out)
        parts.append(parser.flush())
        text = "".join(parts).strip()
        if not text:
            return None

        async with self._sessions() as db:
            msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=text,
                emotion=emotion or "normal",
                interface="proactive",
            )
            db.add(msg)
            await db.commit()
            message_id = msg.id

        return {
            "conversation_id": conversation.id,
            "message_id": message_id,
            "text": text,
            "emotion": emotion or "normal",
        }

    async def _run_tool(self, tool_call: dict) -> tuple[str, str]:
        """ツールを実行し (状態, LLMへ返す結果文字列) を返す。例外は結果文字列に変換"""
        name = tool_call["name"]
        try:
            args = json.loads(tool_call.get("arguments") or "{}")
        except json.JSONDecodeError:
            return "error", f"ツール引数のJSONが不正です: {tool_call.get('arguments')}"
        try:
            result = await self._plugins.execute_tool(name, args)
        except Exception as e:  # noqa: BLE001 - ツール失敗はLLMに伝えて会話は継続
            logger.exception("ツール %s の実行に失敗", name)
            return "error", f"ツール実行エラー: {e}"
        if isinstance(result, str):
            return "done", result
        return "done", json.dumps(result, ensure_ascii=False, default=str)

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
