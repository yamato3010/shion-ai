"""音声合成 REST API(VOICEVOX proxy)"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter()


class SpeechRequest(BaseModel):
    text: str


@router.get("/voice/status")
async def voice_status(request: Request):
    voice = request.app.state.voice
    return {
        "enabled": voice.enabled,
        "available": await voice.is_available(),
        "speaker": voice.speaker,
    }


@router.post("/voice")
async def synthesize(body: SpeechRequest, request: Request):
    voice = request.app.state.voice
    if not voice.enabled:
        raise HTTPException(status_code=400, detail="音声は無効化されています(config.yaml の voice.enabled)")
    wav = await voice.synthesize(body.text)
    if wav is None:
        raise HTTPException(
            status_code=503,
            detail="音声合成できません(VOICEVOX Engine が起動しているか確認)",
        )
    return Response(content=wav, media_type="audio/wav")
