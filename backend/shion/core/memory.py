"""Memory Manager: 長期記憶(docs/02 §5.3)

- 会話後に「保存すべき事実」をLLM(purpose="memory")で抽出して保存
- 応答生成前にユーザー発話との類似検索で上位k件をプロンプトへ注入
- ベクトル検索は埋め込みをSQLiteに持ちプロセス内でコサイン類似度を計算する
  (個人利用規模では十分。埋め込みが使えない環境では文字bigramの重なりで代用)

設計書のChroma採用からの変更: 依存を増やさずバックアップも shion.db 1ファイルで
済むため、当面はSQLite内蔵とする。件数が増えて遅くなったらChromaへ差し替える。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.db.models import Memory
from shion.llm import LLMRouter
from shion.llm import Message as LLMMessage

logger = logging.getLogger(__name__)

CATEGORIES = ("profile", "preference", "relationship", "event", "task", "other")

EXTRACT_PROMPT = """あなたは会話ログから「長期的に覚えておくべき事実」を抽出する係です。
以下の会話から、ユーザーに関する持続的な事実(プロフィール・好み・人間関係・予定・依頼・環境など)を抽出し、
JSON配列のみを出力してください。各要素は {"content": "事実の簡潔な一文", "category": "profile|preference|relationship|event|task|other"}。

ルール:
- 挨拶・一時的な話題・その場限りの質問は保存しない
- 事実は第三者が読んでも分かる自己完結した一文にする(例: 「ユーザーは大阪出身」)
- 保存すべきものが無ければ [] とだけ出力する

# 会話
{conversation}
"""


def _bigrams(text: str) -> set[str]:
    t = "".join(text.lower().split())
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else {t} if t else set()


# 漢字・カタカナ・英数字は1文字/1語でも内容を担う(「犬の話」と「犬を飼う」の照合用)
_CONTENT_CHAR_RE = re.compile(r"[一-鿿゠-ヿ]|[a-zA-Z0-9]+")


def _content_chars(text: str) -> set[str]:
    return set(_CONTENT_CHAR_RE.findall(text.lower()))


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _keyword_score(query: str, content: str) -> float:
    """埋め込みが使えないときの類似度。bigram一致と内容文字一致の高い方を採る"""
    return max(
        _jaccard(_bigrams(query), _bigrams(content)),
        _jaccard(_content_chars(query), _content_chars(content)),
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class MemoryManager:
    # これ以上類似する記憶が既にあれば重複とみなして保存しない
    DUP_COSINE = 0.92
    DUP_BIGRAM = 0.8

    def __init__(self, session_factory: async_sessionmaker, llm: LLMRouter) -> None:
        self._sessions = session_factory
        self._llm = llm

    # --- 保存 ---

    async def store(self, content: str, category: str = "other", source: str = "chat") -> Memory | None:
        """1件保存する。既存とほぼ同内容なら保存せず None を返す"""
        content = content.strip()
        if not content:
            return None
        if category not in CATEGORIES:
            category = "other"

        vectors = await self._llm.embed([content])
        embedding = vectors[0] if vectors else None

        if await self._is_duplicate(content, embedding):
            logger.debug("重複記憶のためスキップ: %s", content)
            return None

        memory = Memory(
            content=content,
            category=category,
            source=source,
            embedding_json=json.dumps(embedding) if embedding else None,
        )
        async with self._sessions() as db:
            db.add(memory)
            await db.commit()
        logger.info("記憶を保存: [%s] %s", category, content)
        return memory

    async def _is_duplicate(self, content: str, embedding: list[float] | None) -> bool:
        rows = await self._all()
        if embedding is not None:
            for row in rows:
                if row.embedding_json:
                    if _cosine(embedding, json.loads(row.embedding_json)) >= self.DUP_COSINE:
                        return True
                elif row.content == content:
                    return True
            return False
        query_grams = _bigrams(content)
        for row in rows:
            grams = _bigrams(row.content)
            union = query_grams | grams
            if union and len(query_grams & grams) / len(union) >= self.DUP_BIGRAM:
                return True
        return False

    # --- 検索 ---

    async def search(self, query: str, k: int = 5) -> list[Memory]:
        """query に関連する記憶を上位k件返す(0件もありうる)"""
        rows = await self._all()
        if not rows:
            return []

        vectors = await self._llm.embed([query])
        if vectors:
            qvec = vectors[0]
            scored = [
                (_cosine(qvec, json.loads(r.embedding_json)), r)
                for r in rows
                if r.embedding_json
            ]
            threshold = 0.2
        else:
            scored = [(_keyword_score(query, r.content), r) for r in rows]
            threshold = 0.05

        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits = [r for score, r in scored[:k] if score >= threshold]
        if hits:
            now = datetime.now(timezone.utc)
            for r in hits:  # 返却オブジェクトはセッション切離し済みのため自前で反映
                r.last_accessed_at = now
            await self._touch([r.id for r in hits], now)
        return hits

    async def _touch(self, ids: list[int], now: datetime) -> None:
        async with self._sessions() as db:
            for row in (
                await db.execute(select(Memory).where(Memory.id.in_(ids)))
            ).scalars():
                row.last_accessed_at = now
            await db.commit()

    # --- 抽出(会話後に非同期で呼ばれる) ---

    async def extract_from_exchange(self, user_text: str, reply_text: str) -> int:
        """1往復の会話から記憶を抽出して保存し、保存件数を返す"""
        if not self._llm.has_real_llm("memory"):
            return 0  # モックLLMしか使えない環境では抽出できない

        conversation = f"ユーザー: {user_text}\n紫桜: {reply_text}"
        prompt = EXTRACT_PROMPT.replace("{conversation}", conversation)
        parts: list[str] = []
        async for chunk in self._llm.stream(
            [LLMMessage(role="user", content=prompt)], purpose="memory"
        ):
            if chunk.text:
                parts.append(chunk.text)
        facts = self._parse_facts("".join(parts))

        saved = 0
        for fact in facts:
            if await self.store(fact["content"], fact.get("category", "other")):
                saved += 1
        return saved

    @staticmethod
    def _parse_facts(text: str) -> list[dict]:
        """LLM出力からJSON配列部分を取り出す。パース不能は「保存なし」扱い"""
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.debug("記憶抽出のJSONパースに失敗: %s", text[:200])
            return []
        return [
            f for f in data
            if isinstance(f, dict) and isinstance(f.get("content"), str) and f["content"].strip()
        ]

    # --- プロンプト注入・管理API用 ---

    @staticmethod
    def format_for_prompt(memories: list[Memory]) -> str:
        lines = [f"- ({m.created_at:%Y-%m-%d}) {m.content}" for m in memories]
        return "## 長期記憶(あなたが覚えていること)\n" + "\n".join(lines)

    async def list_all(self) -> list[Memory]:
        return await self._all(order_desc=True)

    async def remove(self, memory_id: int) -> None:
        async with self._sessions() as db:
            await db.execute(delete(Memory).where(Memory.id == memory_id))
            await db.commit()

    async def count(self) -> int:
        return len(await self._all())

    async def _all(self, order_desc: bool = False) -> list[Memory]:
        stmt = select(Memory)
        if order_desc:
            stmt = stmt.order_by(Memory.id.desc())
        async with self._sessions() as db:
            return list((await db.execute(stmt)).scalars().all())


def spawn_extraction(memory: MemoryManager, user_text: str, reply_text: str, tasks: set) -> None:
    """記憶抽出を fire-and-forget で起動する(応答ストリームをブロックしない)"""

    async def run():
        try:
            await memory.extract_from_exchange(user_text, reply_text)
        except Exception:  # noqa: BLE001 - 抽出失敗は会話に影響させない
            logger.exception("記憶抽出に失敗")

    task = asyncio.create_task(run())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
