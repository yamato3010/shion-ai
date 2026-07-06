"""人格定義のロードと感情タグ処理(docs/01 FR-10, docs/05 §1.3)"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

DEFAULT_EMOTIONS = ["normal", "joy", "sad", "surprised", "troubled", "shy", "thinking"]


class Persona:
    def __init__(self, data: dict) -> None:
        self.name: str = data.get("name", "紫桜")
        self.emotions: list[str] = data.get("emotions") or DEFAULT_EMOTIONS
        self._system_prompt: str = data.get("system_prompt", "")
        self._emotion_instruction: str = data.get("emotion_instruction", "")

    @classmethod
    def load(cls, path: Path) -> "Persona":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(data or {})

    def build_system_prompt(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d (%a) %H:%M")
        parts = [
            self._system_prompt.strip(),
            f"## 現在の状況\n- 現在日時: {now}",
            self._emotion_instruction.strip(),
        ]
        return "\n\n".join(p for p in parts if p)


class EmotionTagParser:
    """ストリーミング出力の先頭から `[joy]` 形式の感情タグを取り出すパーサ。

    タグはチャンク境界をまたいで届く可能性があるため、タグ確定までバッファする。
    """

    MAX_TAG_BUFFER = 24  # これを超えて ']' が来なければタグではないと判断

    def __init__(self, allowed: list[str]) -> None:
        self._allowed = set(allowed)
        self._buffer = ""
        self._resolved = False
        self.emotion: str | None = None

    def feed(self, text: str) -> tuple[str, str | None]:
        """テキスト片を受け取り、(出力してよいテキスト, 新たに確定した感情) を返す"""
        if self._resolved:
            return text, None

        self._buffer += text
        if not self._buffer.startswith("["):
            return self._flush_as_text(), None

        end = self._buffer.find("]")
        if end == -1:
            if len(self._buffer) > self.MAX_TAG_BUFFER:
                return self._flush_as_text(), None
            return "", None  # タグ確定待ち

        tag = self._buffer[1:end]
        if tag not in self._allowed:
            return self._flush_as_text(), None

        rest = self._buffer[end + 1 :].lstrip()
        self._buffer = ""
        self._resolved = True
        self.emotion = tag
        return rest, tag

    def flush(self) -> str:
        """ストリーム終端で未出力のバッファを回収する"""
        if self._resolved:
            return ""
        return self._flush_as_text()

    def _flush_as_text(self) -> str:
        out = self._buffer
        self._buffer = ""
        self._resolved = True
        return out
