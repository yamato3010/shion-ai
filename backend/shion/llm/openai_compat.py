"""OpenAI互換 chat/completions プロバイダ。

OpenAI / Gemini(OpenAI互換エンドポイント)/ Ollama(/v1)をこれ1つでカバーする。
将来ネイティブSDKが必要になったらプロバイダを分離する(docs/04_llm_provider.md)。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from shion.llm.base import GenerationChunk, LLMError, LLMProvider, Message, ToolSpec


class OpenAICompatProvider(LLMProvider):
    def __init__(self, name: str, api_key: str, base_url: str) -> None:
        self.name = name
        self._api_key = api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def generate(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSpec] | None = None,
        **params,
    ) -> AsyncIterator[GenerationChunk]:
        if not self._api_key:
            raise LLMError(f"プロバイダ '{self.name}' のAPIキーが未設定です(.env を確認)")

        payload: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            **params,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"{self.name}/{model} HTTP {resp.status_code}: {body[:300]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    obj = json.loads(data)
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield GenerationChunk(text=text)
                    finish = choices[0].get("finish_reason")
                    if finish:
                        yield GenerationChunk(finish_reason=finish, usage=obj.get("usage"))
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}/{model} への接続に失敗: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
