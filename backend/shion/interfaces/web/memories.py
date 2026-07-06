"""長期記憶の管理 REST API(一覧・手動追加・削除)"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class MemoryCreate(BaseModel):
    content: str
    category: str = "other"


def _to_dict(m) -> dict:
    return {
        "id": m.id,
        "content": m.content,
        "category": m.category,
        "source": m.source,
        "created_at": m.created_at.isoformat(),
        "last_accessed_at": m.last_accessed_at.isoformat() if m.last_accessed_at else None,
    }


@router.get("/memories")
async def list_memories(request: Request):
    memories = await request.app.state.memory.list_all()
    return [_to_dict(m) for m in memories]


@router.post("/memories")
async def create_memory(body: MemoryCreate, request: Request):
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="内容が空です")
    memory = await request.app.state.memory.store(
        body.content, category=body.category, source="manual"
    )
    if memory is None:
        raise HTTPException(status_code=409, detail="ほぼ同じ内容の記憶が既にあります")
    return _to_dict(memory)


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, request: Request):
    await request.app.state.memory.remove(memory_id)
    return {"ok": True}
