"""Anthropicプロバイダのメッセージ形式変換のテスト"""

from shion.llm.anthropic import convert_messages, convert_tools
from shion.llm.base import Message, ToolSpec


def test_system_and_plain_messages():
    system, messages = convert_messages(
        [
            Message(role="system", content="あなたは紫桜"),
            Message(role="user", content="こんにちは"),
            Message(role="assistant", content="やっほー"),
        ]
    )
    assert system == "あなたは紫桜"
    assert messages == [
        {"role": "user", "content": "こんにちは"},
        {"role": "assistant", "content": "やっほー"},
    ]


def test_tool_call_and_result_conversion():
    system, messages = convert_messages(
        [
            Message(role="user", content="東京の天気は?"),
            Message(
                role="assistant",
                content="調べるね",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"location": "Tokyo"}'},
                    }
                ],
            ),
            Message(role="tool", content='{"weather": "晴れ"}', tool_call_id="call_1"),
            Message(role="tool", content="2件目", tool_call_id="call_2"),
        ]
    )
    assistant = messages[1]
    assert assistant["content"][0] == {"type": "text", "text": "調べるね"}
    assert assistant["content"][1] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "get_weather",
        "input": {"location": "Tokyo"},
    }
    # 連続する tool_result は1つの user メッセージへまとめる(role交互の制約)
    results = messages[2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["call_1", "call_2"]


def test_broken_tool_arguments_become_empty_input():
    _, messages = convert_messages(
        [
            Message(
                role="assistant",
                content="",
                tool_calls=[{"id": "x", "type": "function", "function": {"name": "f", "arguments": "{oops"}}],
            )
        ]
    )
    assert messages[0]["content"][0]["input"] == {}


def test_convert_tools():
    specs = [ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})]
    assert convert_tools(specs) == [
        {"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}
    ]
    assert convert_tools(None) is None
