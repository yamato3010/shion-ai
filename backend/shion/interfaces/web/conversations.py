"""会話履歴 REST API(docs/05 §1.4)"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select

from shion.db.models import Conversation, Message

router = APIRouter()


@router.get("/conversations")
async def list_conversations(request: Request):
    async with request.app.state.sessions() as db:
        rows = (
            await db.execute(select(Conversation).order_by(Conversation.id.desc()))
        ).scalars().all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, request: Request):
    async with request.app.state.sessions() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="会話が見つかりません")
        rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            )
        ).scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "emotion": m.emotion,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, request: Request):
    async with request.app.state.sessions() as db:
        await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await db.commit()
    return {"ok": True}
