"""プラグインローダとツール実行のテスト"""

import asyncio
import textwrap

import pytest

from shion.core.events import EventBus
from shion.core.scheduler import Scheduler
from shion.db.session import init_db, make_engine, make_session_factory
from shion.llm import LLMRouter
from shion.plugins.loader import PluginManager, build_tool_parameters


def test_build_tool_parameters():
    async def sample(self, location: str, days: int = 3, verbose: bool = False):
        pass

    schema = build_tool_parameters(sample)
    assert schema["type"] == "object"
    assert schema["properties"]["location"] == {"type": "string"}
    assert schema["properties"]["days"] == {"type": "integer", "default": 3}
    assert schema["properties"]["verbose"] == {"type": "boolean", "default": False}
    assert schema["required"] == ["location"]


PLUGIN_YAML = """
name: echo
display_name: エコー
version: 1.0.0
description: テスト用
api_version: 1
config_schema:
  prefix:
    type: string
    default: "echo:"
"""

PLUGIN_PY = '''
from shion.plugins import PluginBase, tool, job

class EchoPlugin(PluginBase):
    loaded = False

    async def on_load(self):
        self.loaded = True

    @tool(description="入力をそのまま返す")
    async def echo(self, text: str) -> str:
        return self.config["prefix"] + text

    @job(cron="0 7 * * *")
    async def daily_echo(self):
        await self.notify(title="echo", body="daily", channel="daily")
'''


@pytest.fixture()
def plugin_env(tmp_path):
    plugins_dir = tmp_path / "plugins"
    (plugins_dir / "echo").mkdir(parents=True)
    (plugins_dir / "echo" / "plugin.yaml").write_text(textwrap.dedent(PLUGIN_YAML), encoding="utf-8")
    (plugins_dir / "echo" / "plugin.py").write_text(textwrap.dedent(PLUGIN_PY), encoding="utf-8")

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = make_session_factory(engine)
    asyncio.run(init_db(engine))

    manager = PluginManager(
        plugins_dir=plugins_dir,
        session_factory=sessions,
        llm=LLMRouter({}),
        events=EventBus(),
        scheduler=Scheduler(sessions),
    )
    return manager


def test_discover_registers_disabled_by_default(plugin_env):
    manager = plugin_env
    asyncio.run(manager.setup())
    info = manager.plugins["echo"]
    assert info.enabled is False
    assert info.status == "disabled"
    assert manager.get_toolspecs() == []


def test_enable_load_and_execute_tool(plugin_env):
    manager = plugin_env

    async def scenario():
        await manager.setup()
        info = await manager.set_enabled("echo", True)
        assert info.status == "loaded", info.error
        assert info.tool_names == ["echo"]
        assert [j["name"] for j in info.jobs] == ["daily_echo"]
        assert [t.name for t in manager.get_toolspecs()] == ["echo"]

        result = await manager.execute_tool("echo", {"text": "hello"})
        assert result == "echo:hello"

        # 設定変更 → リロード後に反映される
        info = await manager.update_config("echo", {"prefix": "id:"})
        assert info.status == "loaded"
        result = await manager.execute_tool("echo", {"text": "1"})
        assert result == "id:1"

        # 無効化でツールが消える
        info = await manager.set_enabled("echo", False)
        assert info.status == "disabled"
        assert manager.get_toolspecs() == []

    asyncio.run(scenario())


def test_broken_plugin_isolated(plugin_env, tmp_path):
    manager = plugin_env
    broken = tmp_path / "plugins" / "broken"
    broken.mkdir()
    (broken / "plugin.yaml").write_text("name: broken\napi_version: 1\n", encoding="utf-8")
    (broken / "plugin.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    async def scenario():
        await manager.setup()
        info = await manager.set_enabled("broken", True)
        assert info.status == "error"
        assert "boom" in (info.error or "")
        # 他のプラグインには影響しない
        info2 = await manager.set_enabled("echo", True)
        assert info2.status == "loaded"

    asyncio.run(scenario())
