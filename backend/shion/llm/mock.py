"""組み込みモックプロバイダ。

APIキー無しで UI・ストリーミング・感情タグの動作確認をするためのもの。
config.yaml の fallback に mock/echo を入れておくと、キー未設定でも会話できる。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from shion.llm.base import GenerationChunk, LLMProvider, Message, ToolSpec


class MockProvider(LLMProvider):
    name = "mock"

    async def generate(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSpec] | None = None,
        **params,
    ) -> AsyncIterator[GenerationChunk]:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        snippet = last_user.replace("\n", " ")[:40]
        reply = (
            f"[shy]えっと……いまはモックモードなの。「{snippet}」って言ってくれたのは聞こえてるよ!"
            " .env にAPIキーを設定して config.yaml のモデルを選ぶと、ほんとのわたしとお話できるからね🌸"
        )
        for i in range(0, len(reply), 6):
            await asyncio.sleep(0.03)
            yield GenerationChunk(text=reply[i : i + 6])
        yield GenerationChunk(finish_reason="stop")
