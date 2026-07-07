"""長期記憶(MemoryManager)のテスト: 保存・重複排除・検索・抽出"""

import asyncio
import json

import pytest

from shion.core.memory import MemoryManager
from shion.db.session import init_db, make_engine, make_session_factory
from shion.llm import GenerationChunk


class FakeRouter:
    """埋め込みと記憶抽出を差し替えられるフェイクLLMルータ"""

    def __init__(self, vectors: dict[str, list[float]] | None = None, extract_output: str = "[]"):
        self.vectors = vectors  # None なら埋め込み不可(キーワード検索フォールバック)
        self.extract_output = extract_output
        self.stream_calls = 0

    async def embed(self, texts):
        if self.vectors is None:
            return None
        return [self.vectors.get(t, [0.0, 0.0, 1.0]) for t in texts]

    def has_real_llm(self, purpose="chat"):
        return True

    async def stream(self, messages, purpose="chat", tools=None, **params):
        self.stream_calls += 1
        yield GenerationChunk(text=self.extract_output)
        yield GenerationChunk(finish_reason="stop")


@pytest.fixture
def sessions(tmp_path):
    async def make():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await init_db(engine)
        return make_session_factory(engine)

    return asyncio.run(make())


def test_store_and_duplicate_skip(sessions):
    async def scenario():
        mm = MemoryManager(sessions, FakeRouter(vectors={}))
        first = await mm.store("ユーザーは大阪出身", "profile")
        assert first is not None
        # 同一内容(=同一ベクトル)は重複としてスキップ
        second = await mm.store("ユーザーは大阪出身", "profile")
        assert second is None
        assert await mm.count() == 1

    asyncio.run(scenario())


def test_vector_search_ranking(sessions):
    async def scenario():
        vectors = {
            "ユーザーは犬を飼っている": [1.0, 0.0, 0.0],
            "ユーザーは毎朝コーヒーを飲む": [0.0, 1.0, 0.0],
            "犬の話": [0.9, 0.1, 0.0],  # クエリ: 犬の記憶に近い
        }
        mm = MemoryManager(sessions, FakeRouter(vectors=vectors))
        await mm.store("ユーザーは犬を飼っている", "profile")
        await mm.store("ユーザーは毎朝コーヒーを飲む", "preference")

        hits = await mm.search("犬の話", k=1)
        assert [h.content for h in hits] == ["ユーザーは犬を飼っている"]
        assert hits[0].last_accessed_at is not None

    asyncio.run(scenario())


def test_keyword_fallback_search(sessions):
    async def scenario():
        mm = MemoryManager(sessions, FakeRouter(vectors=None))  # 埋め込み不可
        await mm.store("ユーザーの誕生日は3月14日")
        await mm.store("ユーザーは紅茶よりコーヒー派")
        await mm.store("ユーザーは犬を飼っている")

        hits = await mm.search("誕生日っていつだっけ")
        assert hits and hits[0].content == "ユーザーの誕生日は3月14日"

        # 助詞が違ってbigramが重ならなくても、漢字ユニグラムで拾える
        hits = await mm.search("うちの犬の話、覚えてる?")
        assert hits and hits[0].content == "ユーザーは犬を飼っている"

    asyncio.run(scenario())


def test_extract_from_exchange(sessions):
    async def scenario():
        output = '抽出結果です。\n[{"content": "ユーザーは京都に住んでいる", "category": "profile"}]'
        router = FakeRouter(vectors={}, extract_output=output)
        mm = MemoryManager(sessions, router)
        saved = await mm.extract_from_exchange("京都に引っ越したんだ", "そうなんだ!")
        assert saved == 1
        assert (await mm.list_all())[0].content == "ユーザーは京都に住んでいる"

    asyncio.run(scenario())


def test_extract_skipped_on_mock(sessions):
    async def scenario():
        router = FakeRouter(vectors={})
        router.has_real_llm = lambda purpose="chat": False
        mm = MemoryManager(sessions, router)
        saved = await mm.extract_from_exchange("こんにちは", "やっほー")
        assert saved == 0
        assert router.stream_calls == 0  # LLM自体呼ばれない

    asyncio.run(scenario())


def test_parse_facts_garbage():
    assert MemoryManager._parse_facts("モックモードなの。") == []
    assert MemoryManager._parse_facts("[]") == []
    assert MemoryManager._parse_facts('[{"content": ""}, {"content": "有効", "category": "task"}, "壊れ"]') == [
        {"content": "有効", "category": "task"}
    ]
    assert MemoryManager._parse_facts(json.dumps([{"content": "a"}])) == [{"content": "a"}]
