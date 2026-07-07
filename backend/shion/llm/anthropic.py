"""Anthropic Messages API プロバイダ(docs/04)

Claude は OpenAI 互換エンドポイントを持たないためネイティブ実装。
tool_use / tool_result を OpenAI 形式の内部表現(Message / GenerationChunk)へ正規化する。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from shion.llm.base import GenerationChunk, LLMError, LLMProvider, Message, ToolSpec

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


def convert_messages(messages: list[Message]) -> tuple[str, list[dict]]:
    """内部表現(OpenAI形式)を Anthropic 形式 (system, messages) へ変換する"""
    system = ""
    converted: list[dict] = []
    for m in messages:
        if m.role == "system":
            system = m.content or ""
            continue
        if m.role == "assistant" and m.tool_calls:
            blocks: list[dict] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                fn = tc.get("function") or {}
                try:
                    tool_input = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    tool_input = {}
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": fn.get("name", ""), "input": tool_input}
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        if m.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id,
                "content": m.content or "",
            }
            # Anthropicはrole交互が必須のため、連続するtool_resultは直前のuserメッセージへまとめる
            if (
                converted
                and converted[-1]["role"] == "user"
                and isinstance(converted[-1]["content"], list)
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        converted.append({"role": m.role, "content": m.content or ""})
    return system, converted


def convert_tools(tools: list[ToolSpec] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in tools
    ]


STOP_REASON_MAP = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


class AnthropicProvider(LLMProvider):
    def __init__(self, name: str, api_key: str, base_url: str = "https://api.anthropic.com") -> None:
        self.name = name
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSpec] | None = None,
        **params,
    ) -> AsyncIterator[GenerationChunk]:
        if not self._api_key:
            raise LLMError(f"プロバイダ '{self.name}' のAPIキーが未設定です(.env を確認)")

        system, converted = convert_messages(messages)
        payload: dict = {
            "model": model,
            "messages": converted,
            "max_tokens": params.pop("max_tokens", DEFAULT_MAX_TOKENS),
            "stream": True,
            **params,
        }
        if system:
            payload["system"] = system
        anthropic_tools = convert_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        usage: dict = {}
        # index → 集約中の tool_use ブロック
        tool_blocks: dict[int, dict] = {}
        try:
            async with self._client.stream("POST", "/v1/messages", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"{self.name}/{model} HTTP {resp.status_code}: {body[:300]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    etype = event.get("type")

                    if etype == "message_start":
                        usage.update((event.get("message") or {}).get("usage") or {})
                    elif etype == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            tool_blocks[event["index"]] = {
                                "id": block.get("id"),
                                "name": block.get("name", ""),
                                "arguments": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield GenerationChunk(text=delta["text"])
                        elif delta.get("type") == "input_json_delta":
                            block = tool_blocks.get(event["index"])
                            if block is not None:
                                block["arguments"] += delta.get("partial_json") or ""
                    elif etype == "content_block_stop":
                        block = tool_blocks.pop(event["index"], None)
                        if block is not None:
                            yield GenerationChunk(tool_call=block)
                    elif etype == "message_delta":
                        usage.update(event.get("usage") or {})
                        stop = (event.get("delta") or {}).get("stop_reason")
                        if stop:
                            yield GenerationChunk(
                                finish_reason=STOP_REASON_MAP.get(stop, stop),
                                usage=usage or None,
                            )
                    elif etype == "error":
                        err = event.get("error") or {}
                        raise LLMError(f"{self.name}/{model}: {err.get('message', 'stream error')}")
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}/{model} への接続に失敗: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
