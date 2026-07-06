"""Discord向けメッセージ整形のテスト"""

from shion.interfaces.discord.format import (
    DISCORD_LIMIT,
    clip_streaming,
    emotion_prefix,
    split_message,
)


def test_emotion_prefix():
    assert emotion_prefix("joy") == "😊"
    assert emotion_prefix(None) == "🌸"
    assert emotion_prefix("unknown") == "🌸"


def test_split_short_message():
    assert split_message("こんにちは") == ["こんにちは"]
    assert split_message("   ") == ["……"]


def test_split_long_message_prefers_newline():
    text = ("あ" * 1500) + "\n" + ("い" * 1000)
    parts = split_message(text)
    assert parts == ["あ" * 1500, "い" * 1000]
    assert all(len(p) <= DISCORD_LIMIT for p in parts)


def test_split_no_boundary():
    text = "x" * 4500
    parts = split_message(text)
    assert len(parts) == 3
    assert "".join(parts) == text
    assert all(len(p) <= DISCORD_LIMIT for p in parts)


def test_clip_streaming():
    assert clip_streaming("生成中") == "生成中 …"
    clipped = clip_streaming("y" * 3000)
    assert len(clipped) <= DISCORD_LIMIT
    assert clipped.endswith("… …")
