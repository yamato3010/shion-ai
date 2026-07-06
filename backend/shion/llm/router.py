"""LLM Router: 用途別モデル解決・フォールバック(docs/04_llm_provider.md)"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from shion.llm.base import GenerationChunk, LLMError, LLMProvider, Message, ToolSpec
from shion.llm.mock import MockProvider
from shion.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self, llm_config: dict | None) -> None:
        self._config = llm_config or {}
        self._providers: dict[str, LLMProvider] = {}

    def _get_provider(self, name: str) -> LLMProvider:
        if name in self._providers:
            return self._providers[name]
        if name == "mock":
            provider: LLMProvider = MockProvider()
        else:
            cfg = (self._config.get("providers") or {}).get(name)
            if cfg is None:
                raise LLMError(f"プロバイダ '{name}' が config.yaml に定義されていません")
            provider = OpenAICompatProvider(
                name=name,
                api_key=cfg.get("api_key") or "",
                base_url=cfg.get("base_url") or "https://api.openai.com/v1",
            )
        self._providers[name] = provider
        return provider

    def _model_specs(self, purpose: str) -> list[str]:
        """purpose に対する 'provider/model' の候補リスト(先頭が本命、以降フォールバック)"""
        models = self._config.get("models") or {}
        primary = models.get(purpose) or models.get("chat")
        specs: list[str] = [primary] if primary else []
        specs += self._config.get("fallback") or []
        if not specs:
            specs = ["mock/echo"]
        return specs

    async def stream(
        self,
        messages: list[Message],
        purpose: str = "chat",
        tools: list[ToolSpec] | None = None,
        **params,
    ) -> AsyncIterator[GenerationChunk]:
        last_error: Exception | None = None
        for spec in self._model_specs(purpose):
            provider_name, _, model = spec.partition("/")
            try:
                provider = self._get_provider(provider_name)
            except LLMError as e:
                last_error = e
                logger.warning("provider解決失敗 %s: %s", spec, e)
                continue

            emitted = False
            try:
                async for chunk in provider.generate(messages, model=model, tools=tools, **params):
                    emitted = True
                    yield chunk
                return
            except Exception as e:  # noqa: BLE001 - フォールバックのため広く捕捉
                if emitted:
                    # 出力開始後の失敗はフォールバックすると応答が二重になるため中断
                    raise
                last_error = e
                logger.warning("%s での生成に失敗、フォールバックします: %s", spec, e)

        raise LLMError(f"すべてのLLMプロバイダで生成に失敗しました: {last_error}") from last_error

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()
