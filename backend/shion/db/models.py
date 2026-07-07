"""DBモデル(docs/02_architecture.md §6)。フェーズ0では会話まわりのみ。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="新しい会話")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PluginSetting(Base):
    __tablename__ = "plugin_settings"

    plugin_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)  # 初回発見時は無効(docs/03 §3)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PluginKV(Base):
    __tablename__ = "plugin_kv"

    plugin_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="null")


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_name: Mapped[str] = mapped_column(String(64), index=True)
    job_name: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | error
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class Memory(Base):
    """長期記憶(docs/02 §5.3)。埋め込みはJSON配列で保持し、検索はプロセス内で行う"""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24), default="other")
    # 埋め込みベクトル(JSON配列)。埋め込みモデル未設定時は null でキーワード検索にフォールバック
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageLog(Base):
    """LLM呼び出しの使用量記録(docs/04 §3)。コストは単価表からの概算"""

    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(24), index=True)  # chat | summarize | memory | embedding
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(default=0.0)  # USD
    estimated: Mapped[bool] = mapped_column(default=False)  # プロバイダがusage未報告で文字数から概算
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OAuthToken(Base):
    """外部サービスのOAuthトークン(暗号化して保存。docs/08)"""

    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)  # 例: google
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    emotion: Mapped[str | None] = mapped_column(String(24), nullable=True)
    interface: Mapped[str] = mapped_column(String(16), default="web")  # web | discord
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
