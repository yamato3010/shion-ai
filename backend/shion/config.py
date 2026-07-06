"""設定ロード。config/config.yaml + .env(docs/02_architecture.md)"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    """config.yaml 内の ${VAR} を環境変数で展開する。未定義は空文字。"""
    if isinstance(value, str):
        return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class Settings:
    def __init__(self, root: Path) -> None:
        self.root = root
        load_dotenv(root / ".env")

        config_path = root / "config" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        self.config: dict = _expand_env(raw or {})

        self.password: str = os.environ.get("SHION_PASSWORD", "shion")
        self.secret_key: str = os.environ.get("SHION_SECRET_KEY", "dev-insecure-secret")

        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_url = f"sqlite+aiosqlite:///{self.data_dir / 'shion.db'}"

    @property
    def llm(self) -> dict:
        return self.config.get("llm") or {}

    @property
    def chat(self) -> dict:
        return self.config.get("chat") or {}

    @classmethod
    def load(cls) -> "Settings":
        root = os.environ.get("SHION_ROOT")
        if root:
            return cls(Path(root))
        # backend/shion/config.py → リポジトリルート
        return cls(Path(__file__).resolve().parents[2])
