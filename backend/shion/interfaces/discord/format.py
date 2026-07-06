"""Discord向けメッセージ整形(docs/05 §2)。純粋関数のみ(単体テスト対象)"""

from __future__ import annotations

DISCORD_LIMIT = 2000

# Discordは表情差分を出せないため、感情タグを絵文字に流用する(docs/05 §2.4)
EMOTION_EMOJI = {
    "normal": "🌸",
    "joy": "😊",
    "sad": "😢",
    "surprised": "😮",
    "troubled": "😥",
    "shy": "☺️",
    "thinking": "🤔",
}


def emotion_prefix(emotion: str | None) -> str:
    return EMOTION_EMOJI.get(emotion or "normal", EMOTION_EMOJI["normal"])


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """2000字制限に合わせて分割する。可能なら改行、次に空白の位置で切る"""
    text = text.strip() or "……"
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 1, limit)
        if cut == -1:
            cut = text.rfind(" ", 1, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    parts.append(text)
    return parts


def clip_streaming(text: str, limit: int = DISCORD_LIMIT) -> str:
    """ストリーミング途中経過の表示用。上限を超える分は末尾を省略する"""
    suffix = " …"
    if len(text) + len(suffix) <= limit:
        return text + suffix
    return text[: limit - len(suffix) - 1] + "…" + suffix
