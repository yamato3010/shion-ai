"""reminder プラグインのテスト(実プラグインをフェイクコンテキストで動かす)"""

import asyncio
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shion.core.events import EventBus
from shion.plugins.base import PluginContext

PLUGIN_PATH = Path(__file__).resolve().parents[2] / "plugins" / "reminder" / "plugin.py"

spec = importlib.util.spec_from_file_location("test_reminder_plugin", PLUGIN_PATH)
reminder_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reminder_mod)


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
def plugin_and_notifications():
    events = EventBus()
    received = []

    async def capture(payload):
        received.append(payload)

    events.subscribe("notification.send", capture)
    ctx = PluginContext(
        name="reminder",
        config={"notify_channel": "important"},
        events=events,
        storage=FakeStorage(),
    )
    return reminder_mod.ReminderPlugin(ctx), received


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def test_parse_when_hhmm_rolls_to_tomorrow():
    past = (datetime.now() - timedelta(hours=1)).strftime("%H:%M")
    parsed = reminder_mod.parse_when(past)
    assert parsed > datetime.now()
    assert parsed.date() == (datetime.now() + timedelta(days=1)).date()


def test_add_list_cancel(plugin_and_notifications):
    plugin, _ = plugin_and_notifications

    async def scenario():
        future = fmt(datetime.now() + timedelta(hours=1))
        result = await plugin.add_reminder(content="お風呂", when=future)
        assert result["registered"]["id"] == 1

        past = fmt(datetime.now() - timedelta(hours=1))
        assert "error" in await plugin.add_reminder(content="過去", when=past)
        assert "error" in await plugin.add_reminder(content="壊れ", when="あした")

        pending = await plugin.list_reminders()
        assert [p["content"] for p in pending] == ["お風呂"]

        assert "cancelled" in await plugin.cancel_reminder(reminder_id=1)
        assert await plugin.list_reminders() == []
        assert "error" in await plugin.cancel_reminder(reminder_id=99)

    asyncio.run(scenario())


def test_check_due_fires_and_notifies(plugin_and_notifications):
    plugin, received = plugin_and_notifications

    async def scenario():
        # ジョブ実行時点で期限を迎えているリマインダーを直接仕込む
        await plugin.storage.set(
            "items",
            [
                {"id": 1, "content": "薬を飲む", "fire_at": fmt(datetime.now() - timedelta(minutes=1)), "status": "pending"},
                {"id": 2, "content": "まだ先", "fire_at": fmt(datetime.now() + timedelta(hours=2)), "status": "pending"},
            ],
        )
        await plugin.check_due()

        assert len(received) == 1
        assert received[0]["body"] == "薬を飲む"
        assert received[0]["channel"] == "important"

        items = await plugin.storage.get("items")
        assert items[0]["status"] == "fired"
        assert items[1]["status"] == "pending"

        # 再実行しても二重通知しない
        await plugin.check_due()
        assert len(received) == 1

    asyncio.run(scenario())


def test_remind_command(plugin_and_notifications):
    plugin, _ = plugin_and_notifications

    async def scenario():
        assert "ないよ" in await plugin.remind_command("")
        future = fmt(datetime.now() + timedelta(hours=1))
        out = await plugin.remind_command(f"{future} 買い物")
        assert "買い物" in out
        listed = await plugin.remind_command("")
        assert "買い物" in listed
        assert "書式" in await plugin.remind_command("そのうち 何か")

    asyncio.run(scenario())
