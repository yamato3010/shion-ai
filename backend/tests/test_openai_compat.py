"""OpenAI互換プロバイダのテスト。

特に Gemini 3 の thought_signature(extra_content)を、ストリーミング応答から
取り込み、次リクエストの assistant.tool_calls へ往復させることを検証する。
"""

import asyncio
import json

import httpx

from shion.llm.base import Message
from shion.llm.openai_compat import OpenAICompatProvider


def _sse(*objs: dict) -> str:
    return "".join(f"data: {json.dumps(o)}\n\n" for o in objs) + "data: [DONE]\n\n"


def _provider_with_body(body: str) -> OpenAICompatProvider:
    provider = OpenAICompatProvider(name="gemini", api_key="k", base_url="https://x/v1")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    provider._client = httpx.AsyncClient(transport=transport, base_url="https://x/v1")
    return provider


def test_streaming_captures_gemini_thought_signature():
    """tool_call の extra_content.google.thought_signature を chunk へ載せて返す"""

    async def scenario():
        body = _sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"location": "Tokyo"}',
                                    },
                                    "extra_content": {"google": {"thought_signature": "SIG123"}},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        )
        provider = _provider_with_body(body)
        tool_calls = []
        async for chunk in provider.generate(
            [Message(role="user", content="東京の天気は?")], model="gemini-3.1-flash-lite"
        ):
            if chunk.tool_call:
                tool_calls.append(chunk.tool_call)
        await provider.close()

        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "get_weather"
        assert tool_calls[0]["extra_content"] == {"google": {"thought_signature": "SIG123"}}

    asyncio.run(scenario())


def test_streaming_without_extra_content_stays_clean():
    """extra_content を返さないプロバイダ(OpenAI等)では tool_call に混入させない"""

    async def scenario():
        body = _sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "f", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        )
        provider = _provider_with_body(body)
        tool_calls = []
        async for chunk in provider.generate(
            [Message(role="user", content="hi")], model="gpt-4o-mini"
        ):
            if chunk.tool_call:
                tool_calls.append(chunk.tool_call)
        await provider.close()

        assert len(tool_calls) == 1
        assert "extra_content" not in tool_calls[0]

    asyncio.run(scenario())


def test_to_message_payload_preserves_extra_content():
    """assistant.tool_calls に載せた extra_content が送信ペイロードへそのまま残る"""
    m = Message(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
                "extra_content": {"google": {"thought_signature": "SIG123"}},
            }
        ],
    )
    payload = OpenAICompatProvider._to_message_payload(m)
    assert payload["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "SIG123"}}
