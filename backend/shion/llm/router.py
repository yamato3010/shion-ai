"""LLM Router: 用途別モデル解決・フォールバック(docs/04_llm_provider.md)"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from shion.llm.anthropic import AnthropicProvider
from shion.llm.base import GenerationChunk, LLMError, LLMProvider, Message, ToolSpec
from shion.llm.mock import MockProvider
from shion.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self, llm_config: dict | None) -> None:
        self._config = llm_config or {}
        self._providers: dict[str, LLMProvider] = {}
        self._embed_warned = False
        self._usage = None  # UsageRecorder(set_usage_recorder で注入)

    def set_usage_recorder(self, recorder) -> None:
        self._usage = recorder

    def _get_provider(self, name: str) -> LLMProvider:
        if name in self._providers:
            return self._providers[name]
        if name == "mock":
            provider: LLMProvider = MockProvider()
        else:
            cfg = (self._config.get("providers") or {}).get(name)
            if cfg is None:
                raise LLMError(f"プロバイダ '{name}' が config.yaml に定義されていません")
            # API方式は type で指定(省略時: anthropic だけネイティブ、他はOpenAI互換)
            api_type = cfg.get("type") or ("anthropic" if name == "anthropic" else "openai_compat")
            if api_type == "anthropic":
                provider = AnthropicProvider(
                    name=name,
                    api_key=cfg.get("api_key") or "",
                    base_url=cfg.get("base_url") or "https://api.anthropic.com",
                )
            else:
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

    def primary_spec(self, purpose: str = "chat") -> str:
        """purpose の本命モデル("provider/model")。/status 表示などに使う"""
        return self._model_specs(purpose)[0]

    def has_real_llm(self, purpose: str = "chat") -> bool:
        """purpose がモック以外の(呼べる見込みのある)LLMに解決されるか。

        記憶抽出やニュース要約のような「モックでは意味がない」処理のスキップ判定に使う。
        """
        for spec in self._model_specs(purpose):
            provider_name, _, _ = spec.partition("/")
            if provider_name == "mock":
                continue
            try:
                if self._get_provider(provider_name).available:
                    return True
            except LLMError:
                continue
        return False

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
            usage: dict | None = None
            out_chars = 0
            try:
                async for chunk in provider.generate(messages, model=model, tools=tools, **params):
                    emitted = True
                    if chunk.usage:
                        usage = chunk.usage
                    if chunk.text:
                        out_chars += len(chunk.text)
                    yield chunk
                await self._record_usage(provider_name, model, purpose, messages, usage, out_chars)
                return
            except Exception as e:  # noqa: BLE001 - フォールバックのため広く捕捉
                if emitted:
                    # 出力開始後の失敗はフォールバックすると応答が二重になるため中断
                    raise
                last_error = e
                logger.warning("%s での生成に失敗、フォールバックします: %s", spec, e)

        raise LLMError(f"すべてのLLMプロバイダで生成に失敗しました: {last_error}") from last_error

    async def _record_usage(
        self,
        provider: str,
        model: str,
        purpose: str,
        messages: list[Message],
        usage: dict | None,
        out_chars: int,
    ) -> None:
        if self._usage is None:
            return
        from shion.core.usage import estimate_tokens

        if usage:
            tokens_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            estimated = False
        else:
            tokens_in = estimate_tokens("".join(m.content or "" for m in messages))
            tokens_out = estimate_tokens("x" * out_chars)
            estimated = True
        await self._usage.record(provider, model, purpose, tokens_in, tokens_out, estimated)

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """埋め込みベクトルを返す。models.embedding 未設定・失敗時は None
        (呼び出し側はキーワード検索等にフォールバックする)"""
        spec = (self._config.get("models") or {}).get("embedding")
        if not spec or not texts:
            return None
        provider_name, _, model = spec.partition("/")
        try:
            provider = self._get_provider(provider_name)
            vectors = await provider.embed(texts, model=model)
            if self._usage is not None:
                from shion.core.usage import estimate_tokens

                await self._usage.record(
                    provider_name,
                    model,
                    "embedding",
                    estimate_tokens("".join(texts)),
                    0,
                    estimated=True,
                )
            return vectors
        except Exception as e:  # noqa: BLE001 - 埋め込み不可は致命的でない
            if not self._embed_warned:
                self._embed_warned = True
                logger.warning("埋め込み(%s)が使えないためキーワード検索にフォールバック: %s", spec, e)
            return None

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()
