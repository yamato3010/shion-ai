"""google_workspaceプラグインの純粋ロジックと、OAuthトークン暗号化保存のテスト"""

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shion.core.oauth_store import OAuthTokenStore
from shion.db.session import init_db, make_engine, make_session_factory

PLUGIN_PATH = Path(__file__).resolve().parents[2] / "plugins" / "google_workspace" / "plugin.py"
spec = importlib.util.spec_from_file_location("test_gw_plugin", PLUGIN_PATH)
gw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gw)


def test_extract_mail_headers():
    message = {
        "id": "m1",
        "snippet": "本文の冒頭…",
        "payload": {
            "headers": [
                {"name": "From", "value": "Amazon <no-reply@amazon.co.jp>"},
                {"name": "Subject", "value": "ご請求金額のお知らせ"},
                {"name": "Date", "value": "Mon, 6 Jul 2026 09:00:00 +0900"},
            ]
        },
    }
    mail = gw.extract_mail_headers(message)
    assert mail["from"] == "Amazon <no-reply@amazon.co.jp>"
    assert mail["subject"] == "ご請求金額のお知らせ"
    assert mail["id"] == "m1"
    assert gw.extract_mail_headers({})["subject"] == "(件名なし)"


def test_is_important_mail():
    mail = {"from": "Boss <boss@example.co.jp>", "subject": "明日の件"}
    assert gw.is_important_mail(mail, ["example.co.jp"], [])  # 送信元ドメイン一致
    assert not gw.is_important_mail(mail, ["other.com"], [])
    assert gw.is_important_mail({"from": "x@y.z", "subject": "【緊急】対応依頼"}, [], ["緊急"])
    assert gw.is_important_mail({"from": "x@y.z", "subject": "Invoice #123"}, [], ["invoice"])  # 大文字小文字無視
    assert not gw.is_important_mail({"from": "x@y.z", "subject": "メルマガ"}, [], ["緊急"])


def test_event_start_and_format():
    timed = {"summary": "MTG", "start": {"dateTime": "2026-07-07T10:00:00+09:00"}, "location": "会議室A"}
    assert gw.event_start(timed) is not None
    assert "MTG" in gw.format_event(timed) and "@会議室A" in gw.format_event(timed)

    all_day = {"summary": "休暇", "start": {"date": "2026-07-07"}}
    assert gw.format_event(all_day).startswith("終日")
    assert gw.event_start({"start": {}}) is None
    assert "(無題の予定)" in gw.format_event({"start": {"date": "2026-07-07"}})


def test_task_helpers():
    assert gw.due_to_rfc3339("") is None
    assert gw.due_to_rfc3339("2026-07-10") == "2026-07-10T00:00:00.000Z"
    import pytest as _pytest

    with _pytest.raises(ValueError):
        gw.due_to_rfc3339("あした")

    assert gw.format_task({"title": "牛乳を買う"}) == "牛乳を買う"
    assert gw.format_task({"title": "レポート", "due": "2026-07-10T00:00:00.000Z"}) == "レポート(期限 2026-07-10)"
    assert gw.format_task({}) == "(無題)"


def test_escape_drive_query():
    assert gw.escape_drive_query("it's a test") == "it\\'s a test"
    assert gw.escape_drive_query("a\\b") == "a\\\\b"
    assert gw.escape_drive_query("普通の検索") == "普通の検索"


def test_to_rfc3339():
    out = gw.to_rfc3339("2026-07-07 10:00")
    assert out.startswith("2026-07-07T10:00:00")
    assert "+" in out or "-" in out[10:]  # タイムゾーンオフセット付き


def test_oauth_store_roundtrip(tmp_path):
    async def scenario():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await init_db(engine)
        sessions = make_session_factory(engine)
        store = OAuthTokenStore(sessions, "secret-key-1")

        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await store.save("google", "access-abc", "refresh-xyz", expires, "gmail calendar")
        token = await store.load("google")
        assert token["access_token"] == "access-abc"
        assert token["refresh_token"] == "refresh-xyz"

        # access更新時に refresh_token=None でも既存refreshは保持される
        await store.save("google", "access-new")
        token = await store.load("google")
        assert token["access_token"] == "access-new"
        assert token["refresh_token"] == "refresh-xyz"

        # 暗号化されて保存されている(平文が入っていない)
        from sqlalchemy import select
        from shion.db.models import OAuthToken

        async with sessions() as db:
            row = (await db.execute(select(OAuthToken))).scalar_one()
        assert "access-new" not in row.access_token_enc
        assert "refresh-xyz" not in (row.refresh_token_enc or "")

        # 鍵が変わったら復号できず None(再連携を促す)
        other = OAuthTokenStore(sessions, "different-key")
        assert await other.load("google") is None

        await store.delete("google")
        assert await store.load("google") is None

    asyncio.run(scenario())
