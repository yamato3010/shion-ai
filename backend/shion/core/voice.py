"""VOICEVOX による音声合成(docs/01 FR-9, docs/02 フェーズ4)

ローカルの VOICEVOX Engine(既定 http://localhost:50021)へ
audio_query → synthesis の2段階リクエストでWAVを得る。
エンジン未起動でも壊れない(is_available で判定し、UI側は静かに無効化)。
"""

from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_URL = "http://localhost:50021"
DEFAULT_SPEAKER = 46  # 小夜/SAYO(ノーマル)。/speakers で一覧確認できる
MAX_SPEECH_CHARS = 400
AVAILABILITY_CACHE_SEC = 30

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_MD_SYMBOLS_RE = re.compile(r"[*#_>|]+")
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff️]"
)


def clean_text_for_speech(text: str, max_chars: int = MAX_SPEECH_CHARS) -> str:
    """読み上げに向かない要素(コード・URL・記号・絵文字)を除去し、長文は文の区切りで打ち切る"""
    text = _CODE_BLOCK_RE.sub("。コードは画面を見てね。", text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = _MD_SYMBOLS_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    # なるべく文末(。!?)で切る
    cut = max(text.rfind(p, 0, max_chars) for p in "。!?!?")
    if cut < max_chars // 2:
        cut = max_chars
    else:
        cut += 1
    return text[:cut]


class VoiceSynthesizer:
    def __init__(self, config: dict | None) -> None:
        cfg = config or {}
        self.enabled: bool = bool(cfg.get("enabled", True))
        self.speaker: int = int(cfg.get("speaker") or DEFAULT_SPEAKER)
        self._client = httpx.AsyncClient(
            base_url=str(cfg.get("engine_url") or DEFAULT_ENGINE_URL).rstrip("/"),
            timeout=httpx.Timeout(60.0, connect=2.0),
        )
        self._available: bool | None = None
        self._checked_at = 0.0

    async def is_available(self) -> bool:
        """エンジンの生存確認(30秒キャッシュ)"""
        if not self.enabled:
            return False
        now = time.monotonic()
        if self._available is not None and now - self._checked_at < AVAILABILITY_CACHE_SEC:
            return self._available
        try:
            resp = await self._client.get("/version")
            self._available = resp.status_code == 200
        except httpx.HTTPError:
            self._available = False
        self._checked_at = now
        return self._available

    async def synthesize(self, text: str) -> bytes | None:
        """テキストをWAVにする。エンジン未起動・空テキストは None"""
        speech_text = clean_text_for_speech(text)
        if not speech_text or not await self.is_available():
            return None
        try:
            query = await self._client.post(
                "/audio_query", params={"text": speech_text, "speaker": self.speaker}
            )
            query.raise_for_status()
            wav = await self._client.post(
                "/synthesis",
                params={"speaker": self.speaker},
                json=query.json(),
                headers={"Content-Type": "application/json"},
            )
            wav.raise_for_status()
            return wav.content
        except httpx.HTTPError as e:
            logger.warning("音声合成に失敗: %s", e)
            self._available = None  # 次回改めて生存確認する
            return None

    async def close(self) -> None:
        await self._client.aclose()
