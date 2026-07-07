"""プロアクティブ会話のテスト(判定ロジック・プラグイン・コアの発話生成)"""

import asyncio
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shion.core.agent import AgentEngine
from shion.core.events import EventBus
from shion.core.persona import Persona
from shion.core.proactive import EVENT_SPEAK, ProactiveSpeaker
from shion.db.session import init_db, make_engine, make_session_factory
from shion.llm import GenerationChunk
from shion.plugins.base import PluginContext

PLUGIN_PATH = Path(__file__).resolve().parents[2] / "plugins" / "proactive" / "plugin.py"
spec = importlib.util.spec_from_file_location("test_proactive_plugin", PLUGIN_PATH)
pro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pro)


def at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 7, 7, hour, minute)


def test_in_active_window():
    assert pro.in_active_window(at("12:00"), "09:00", "23:00")
    assert not pro.in_active_window(at("03:00"), "09:00", "23:00")
    # 日をまたぐ窓(22:00〜02:00)
    assert pro.in_active_window(at("23:30"), "22:00", "02:00")
    assert pro.in_active_window(at("01:00"), "22:00", "02:00")
    assert not pro.in_active_window(at("12:00"), "22:00", "02:00")


def test_should_idle_call():
    now = at("15:00")
    old = now - timedelta(hours=7)
    recent = now - timedelta(hours=1)
    assert pro.should_idle_call(now, old, None, 6)
    assert not pro.should_idle_call(now, recent, None, 6)  # 最近会話した
    assert not pro.should_idle_call(now, old, recent, 6)  # さっき声かけしたばかり
    assert pro.should_idle_call(now, old, now - timedelta(hours=7), 6)
    assert not pro.should_idle_call(now, None, None, 6)  # 一度も会話がない
    assert not pro.should_idle_call(now, old, None, 0)  # 無効化


class FakeStorage:
    def __init__(self):
        self.data = {}

    async def get(self, key, default=None):
        return self.data.get(key, default)

    async def set(self, key, value):
        self.data[key] = value

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def plugin_env():
    events = EventBus()
    spoken = []

    async def capture(payload):
        spoken.append(payload)

    events.subscribe(EVENT_SPEAK, capture)
    ctx = PluginContext(
        name="proactive",
        config={"bedtime": "23:30", "idle_hours": 6, "active_start": "09:00", "active_end": "23:00"},
        events=events,
        storage=FakeStorage(),
    )
    return pro.ProactivePlugin(ctx), spoken, events


def test_plugin_bedtime_and_idle(plugin_env):
    plugin, spoken, events = plugin_env

    async def scenario():
        await plugin.on_load()

        # 会話イベントで最終活動時刻が記録される
        await events.publish("message.received", {"conversation_id": 1, "interface": "web"})
        assert await plugin.storage.get("last_activity") is not None

        # 直後のidle_checkは声かけしない
        assert "スキップ" in await plugin.idle_check()
        assert spoken == []

        # 7時間前の会話にする → 声かけ発生
        stale = (datetime.now() - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
        await plugin.storage.set("last_activity", stale)
        result = await plugin.idle_check()
        if pro.in_active_window(datetime.now(), "09:00", "23:00"):
            assert result == "様子うかがいの声かけ"
            assert len(spoken) == 1
            # 連投しない
            assert "スキップ" in await plugin.idle_check()
            assert len(spoken) == 1

        # 就寝の声かけ
        await plugin.bedtime()
        assert spoken[-1]["plugin"] == "proactive"

    asyncio.run(scenario())


class ProactiveFakeRouter:
    async def stream(self, messages, purpose="chat", tools=None, **params):
        # 指示がuserメッセージとして渡っていることを確認
        assert "指示:" in messages[-1].content
        for piece in ["[joy]", "そろそろ寝る", "時間だよ!"]:
            yield GenerationChunk(text=piece)
        yield GenerationChunk(finish_reason="stop")


def test_proactive_reply_and_speaker(tmp_path):
    async def scenario():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await init_db(engine)
        sessions = make_session_factory(engine)
        events = EventBus()
        agent = AgentEngine(
            router=ProactiveFakeRouter(),
            persona=Persona({"name": "紫桜"}),
            session_factory=sessions,
            events=events,
        )

        broadcasts = []

        class FakeWS:
            async def broadcast(self, payload):
                broadcasts.append(payload)

        ProactiveSpeaker(events, agent, FakeWS())
        await events.publish(EVENT_SPEAK, {"instruction": "寝る時間を優しく知らせて", "plugin": "proactive"})

        assert len(broadcasts) == 1
        ev = broadcasts[0]
        assert ev["type"] == "proactive"
        assert ev["text"] == "そろそろ寝る時間だよ!"
        assert ev["emotion"] == "joy"

        # 会話にassistantメッセージとして保存され、指示文は保存されていない
        from sqlalchemy import select
        from shion.db.models import Message

        async with sessions() as db:
            rows = (await db.execute(select(Message))).scalars().all()
        assert len(rows) == 1
        assert rows[0].role == "assistant"
        assert rows[0].interface == "proactive"

    asyncio.run(scenario())
