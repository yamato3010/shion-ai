"""ダッシュボード REST API(docs/05 §1.1)

プラグインの dashboard() フックが返すカードと、LLM使用量サマリを集約して返す。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(request: Request, days: int = 30):
    cards = await request.app.state.plugin_manager.get_dashboard_cards()
    usage = await request.app.state.usage_recorder.summary(days=max(1, min(days, 365)))
    return {"cards": cards, "usage": usage}
