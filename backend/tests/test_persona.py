from shion.core.persona import DEFAULT_EMOTIONS, EmotionTagParser, Persona


def feed_all(parser: EmotionTagParser, chunks: list[str]) -> tuple[str, str | None]:
    out = []
    emotion = None
    for chunk in chunks:
        text, emo = parser.feed(chunk)
        out.append(text)
        emotion = emotion or emo
    out.append(parser.flush())
    return "".join(out), emotion


def test_tag_in_single_chunk():
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), ["[joy]おかえり!"])
    assert text == "おかえり!"
    assert emotion == "joy"


def test_tag_split_across_chunks():
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), ["[j", "oy", "]こん", "にちは"])
    assert text == "こんにちは"
    assert emotion == "joy"


def test_no_tag():
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), ["こんにちは!"])
    assert text == "こんにちは!"
    assert emotion is None


def test_unknown_tag_passes_through():
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), ["[angry]むー"])
    assert text == "[angry]むー"
    assert emotion is None


def test_bracket_text_without_closing():
    # '[' で始まるが長すぎる → タグではなく本文として扱う
    long_text = "[" + "あ" * 30
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), [long_text])
    assert text == long_text
    assert emotion is None


def test_stream_end_while_buffering():
    # タグ確定前にストリームが終わってもflushで回収される
    text, emotion = feed_all(EmotionTagParser(DEFAULT_EMOTIONS), ["[jo"])
    assert text == "[jo"
    assert emotion is None


def test_persona_prompt_contains_emotion_instruction():
    persona = Persona(
        {
            "name": "紫桜",
            "system_prompt": "あなたは紫桜です。",
            "emotion_instruction": "感情タグを付けてください。",
        }
    )
    prompt = persona.build_system_prompt()
    assert "紫桜" in prompt
    assert "感情タグ" in prompt
    assert "現在日時" in prompt
