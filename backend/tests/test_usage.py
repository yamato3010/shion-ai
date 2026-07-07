"""使用量・コスト記録のテスト"""

import asyncio

from shion.core.usage import UsageRecorder, estimate_tokens
from shion.db.session import init_db, make_engine, make_session_factory


def make_sessions(tmp_path):
    async def scenario():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await init_db(engine)
        return make_session_factory(engine)

    return asyncio.run(scenario())


def test_cost_prefix_match(tmp_path):
    rec = UsageRecorder(make_sessions(tmp_path))
    # 完全一致
    assert rec.cost_of("openai", "gpt-4o-mini", 1_000_000, 0) == 0.15
    # 前方一致(バージョン付きモデル名)
    cost = rec.cost_of("anthropic", "claude-sonnet-5-20250929", 1_000_000, 1_000_000)
    assert cost == 3.00 + 15.00
    # ローカル・モックは無料
    assert rec.cost_of("ollama", "nadeshiko:v1", 1_000_000, 1_000_000) == 0.0
    # 未知モデルは0(落ちない)
    assert rec.cost_of("unknown", "model-x", 1000, 1000) == 0.0


def test_pricing_override(tmp_path):
    rec = UsageRecorder(make_sessions(tmp_path), {"ollama/nadeshiko:v1": {"in": 1.0, "out": 2.0}})
    assert rec.cost_of("ollama", "nadeshiko:v1", 1_000_000, 1_000_000) == 3.0


def test_record_and_summary(tmp_path):
    sessions = make_sessions(tmp_path)
    rec = UsageRecorder(sessions)

    async def scenario():
        await rec.record("openai", "gpt-4o-mini", "chat", 1000, 500)
        await rec.record("openai", "gpt-4o-mini", "chat", 2000, 1000)
        await rec.record("mock", "echo", "chat", 100, 50, estimated=True)
        summary = await rec.summary(days=7)
        assert summary["total_calls"] == 3
        assert summary["total_cost"] > 0
        assert summary["today_cost"] == summary["total_cost"]  # 全部今日の分
        chat_openai = next(
            e for e in summary["entries"] if e["model"] == "gpt-4o-mini"
        )
        assert chat_openai["tokens_in"] == 3000
        assert chat_openai["calls"] == 2

    asyncio.run(scenario())


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("あ" * 300) == 100
