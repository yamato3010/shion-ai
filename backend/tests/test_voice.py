"""音声合成のテキスト前処理のテスト"""

from shion.core.voice import clean_text_for_speech


def test_strips_code_and_urls():
    text = "これを見て ```python\nprint(1)\n``` 詳細は https://example.com/a?x=1 だよ"
    out = clean_text_for_speech(text)
    assert "print" not in out
    assert "https" not in out
    assert "コードは画面を見てね" in out


def test_strips_markdown_and_emoji():
    out = clean_text_for_speech("**大事** な話🌸 `code` #見出し")
    assert out == "大事 な話 見出し"


def test_truncates_at_sentence_boundary():
    text = "こんにちは。" * 200  # 1200文字
    out = clean_text_for_speech(text, max_chars=100)
    assert len(out) <= 100
    assert out.endswith("。")


def test_short_text_unchanged():
    assert clean_text_for_speech("やっほー!元気?") == "やっほー!元気?"
    assert clean_text_for_speech("   ") == ""
