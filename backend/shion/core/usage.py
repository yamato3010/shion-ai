"""使用量・コスト記録(docs/04 §3)

LLM Router が全呼び出しをここへ記録し、単価表(config.yaml の llm.pricing +
組み込みデフォルト)から概算コストを計算する。ダッシュボードの 📊 で可視化。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.db.models import UsageLog

logger = logging.getLogger(__name__)

# USD / 100万トークン(in, out)。config.yaml の llm.pricing で上書き・追加できる。
# キーは "provider/model"。前方一致で解決する(バージョン付きモデル名対策)
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4.1": (2.00, 8.00),
    "openai/text-embedding-3-small": (0.02, 0.0),
    "openai/text-embedding-3-large": (0.13, 0.0),
    "gemini/gemini-2.0-flash": (0.10, 0.40),
    "gemini/gemini-2.5-flash": (0.30, 2.50),
    "gemini/gemini-2.5-pro": (1.25, 10.00),
    "anthropic/claude-haiku": (1.00, 5.00),
    "anthropic/claude-sonnet": (3.00, 15.00),
    "anthropic/claude-opus": (5.00, 25.00),
    "ollama/": (0.0, 0.0),  # ローカルは無料
    "mock/": (0.0, 0.0),
}


def estimate_tokens(text: str) -> int:
    """usage未報告時の概算。日本語混じりで1トークン≒3文字とみなす雑な近似"""
    return max(1, len(text) // 3)


class UsageRecorder:
    def __init__(self, session_factory: async_sessionmaker, pricing: dict | None = None) -> None:
        self._sessions = session_factory
        self._pricing: dict[str, tuple[float, float]] = dict(DEFAULT_PRICING)
        for key, value in (pricing or {}).items():
            if isinstance(value, dict):
                self._pricing[key] = (float(value.get("in", 0)), float(value.get("out", 0)))
            elif isinstance(value, (list, tuple)) and len(value) == 2:
                self._pricing[key] = (float(value[0]), float(value[1]))

    def cost_of(self, provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
        spec = f"{provider}/{model}"
        price = self._pricing.get(spec)
        if price is None:
            # 前方一致で最長マッチ(例: claude-sonnet-5-20250101 → anthropic/claude-sonnet)
            candidates = [k for k in self._pricing if spec.startswith(k)]
            price = self._pricing[max(candidates, key=len)] if candidates else (0.0, 0.0)
        return (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000

    async def record(
        self,
        provider: str,
        model: str,
        purpose: str,
        tokens_in: int,
        tokens_out: int,
        estimated: bool = False,
    ) -> None:
        try:
            async with self._sessions() as db:
                db.add(
                    UsageLog(
                        provider=provider,
                        model=model,
                        purpose=purpose,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_estimate=self.cost_of(provider, model, tokens_in, tokens_out),
                        estimated=estimated,
                    )
                )
                await db.commit()
        except Exception:  # noqa: BLE001 - 記録失敗で生成を止めない
            logger.exception("使用量の記録に失敗")

    async def summary(self, days: int = 30) -> dict:
        """日別・モデル別の集計と合計を返す(ダッシュボード用)"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._sessions() as db:
            rows = (
                await db.execute(
                    select(
                        func.date(UsageLog.created_at).label("date"),
                        UsageLog.provider,
                        UsageLog.model,
                        UsageLog.purpose,
                        func.sum(UsageLog.tokens_in),
                        func.sum(UsageLog.tokens_out),
                        func.sum(UsageLog.cost_estimate),
                        func.count(),
                        func.max(UsageLog.estimated),
                    )
                    .where(UsageLog.created_at >= since)
                    .group_by("date", UsageLog.provider, UsageLog.model, UsageLog.purpose)
                    .order_by(func.date(UsageLog.created_at).desc())
                )
            ).all()
        entries = [
            {
                "date": str(r[0]),
                "provider": r[1],
                "model": r[2],
                "purpose": r[3],
                "tokens_in": int(r[4] or 0),
                "tokens_out": int(r[5] or 0),
                "cost": float(r[6] or 0.0),
                "calls": int(r[7] or 0),
                "has_estimate": bool(r[8]),
            }
            for r in rows
        ]
        today = datetime.now(timezone.utc).date().isoformat()
        return {
            "days": days,
            "total_cost": sum(e["cost"] for e in entries),
            "today_cost": sum(e["cost"] for e in entries if e["date"] == today),
            "total_calls": sum(e["calls"] for e in entries),
            "entries": entries,
        }
