"""LLMプロバイダ共通インターフェース(docs/04_llm_provider.md)"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # assistant がツールを呼ぶとき(OpenAI形式: [{id, type, function:{name, arguments}}])
    tool_calls: list[dict] | None = None
    # role="tool" の結果メッセージが応答するツール呼び出しID
    tool_call_id: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass
class GenerationChunk:
    text: str | None = None
    tool_call: dict | None = None
    finish_reason: str | None = None
    usage: dict | None = None


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSpec] | None = None,
        **params,
    ) -> AsyncIterator[GenerationChunk]:
        """ストリーミング生成。async generator として実装する。"""

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError(f"{self.name} は埋め込みに未対応")

    async def close(self) -> None:
        pass
