"""Agentのツール実行ループのテスト(フェイクLLM・フェイクプラグインで検証)"""

import asyncio
import json

from shion.core.agent import AgentEngine
from shion.core.persona import Persona
from shion.db.session import init_db, make_engine, make_session_factory
from shion.llm import GenerationChunk, ToolSpec


class FakeRouter:
    """1回目はtool_callを返し、tool結果を受けたら最終応答を返すフェイクLLM"""

    def __init__(self):
        self.calls = []

    async def stream(self, messages, purpose="chat", tools=None, **params):
        self.calls.append(messages)
        has_tool_result = any(m.role == "tool" for m in messages)
        if not has_tool_result:
            yield GenerationChunk(
                tool_call={"id": "call_1", "name": "get_weather", "arguments": '{"location": "東京"}'}
            )
            yield GenerationChunk(finish_reason="tool_calls")
        else:
            tool_result = json.loads([m for m in messages if m.role == "tool"][0].content)
            for piece in ["[joy]", "東京は", tool_result["weather"], "だよ!"]:
                yield GenerationChunk(text=piece)
            yield GenerationChunk(finish_reason="stop")


class FakePluginManager:
    def get_toolspecs(self):
        return [ToolSpec(name="get_weather", description="天気", parameters={"type": "object", "properties": {}})]

    async def execute_tool(self, name, args):
        assert name == "get_weather"
        assert args == {"location": "東京"}
        return {"weather": "晴れ"}


def test_agent_tool_loop(tmp_path):
    async def scenario():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await init_db(engine)
        sessions = make_session_factory(engine)
        agent = AgentEngine(
            router=FakeRouter(),
            persona=Persona({"name": "紫桜"}),
            session_factory=sessions,
            plugin_manager=FakePluginManager(),
        )

        events = []
        async for ev in agent.stream_reply(None, "東京の天気は?"):
            events.append(ev)

        types = [e["type"] for e in events]
        assert types[0] == "session"
        assert "tool_status" in types
        statuses = [e["state"] for e in events if e["type"] == "tool_status"]
        assert statuses == ["running", "done"]
        assert next(e["value"] for e in events if e["type"] == "emotion") == "joy"
        reply = "".join(e["text"] for e in events if e["type"] == "chunk")
        assert reply == "東京は晴れだよ!"
        assert events[-1]["type"] == "done"
        assert events[-1]["emotion"] == "joy"

    asyncio.run(scenario())
