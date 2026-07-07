"""Google連携プラグイン(docs/06)

Gmail / Google Calendar を REST(httpx)で直接叩く。認証はコアのOAuthフロー
(Web UIの📊タブ →「Googleと連携」)で保存されたトークンを oauth ストアから
取得し、期限切れは refresh_token で自動更新する。

- Tool: get_events / create_event / search_emails / get_unread_summary
- Job:  morning_briefing(毎朝)/ mail_watch(5分間隔)/ event_reminder(15分間隔)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from shion.plugins import PluginBase, daily_cron, job, tool

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
CAL_BASE = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"

NOTIFIED_MAIL_KEY = "notified_mail_ids"
REMINDED_EVENT_KEY = "reminded_events"
TIME_FMT = "%Y-%m-%d %H:%M"


# --- 純粋ヘルパ(ユニットテスト対象) ---


def extract_mail_headers(message: dict) -> dict:
    """Gmail APIのmessageリソースから From / Subject / 日付 / snippet を取り出す"""
    headers = {
        h["name"].lower(): h["value"]
        for h in (message.get("payload") or {}).get("headers") or []
    }
    return {
        "id": message.get("id", ""),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", "(件名なし)"),
        "date": headers.get("date", ""),
        "snippet": message.get("snippet", ""),
    }


def is_important_mail(mail: dict, important_senders: list, important_keywords: list) -> bool:
    """ルールベースの重要判定(docs/06 §4 の一次フィルタ)"""
    sender = (mail.get("from") or "").lower()
    subject = mail.get("subject") or ""
    for pattern in important_senders or []:
        if str(pattern).lower() in sender:
            return True
    for keyword in important_keywords or []:
        if str(keyword) and str(keyword).lower() in subject.lower():
            return True
    return False


def event_start(event: dict) -> datetime | None:
    """Calendarイベントのstartをローカルのdatetimeにする(不明なら None)"""
    start = event.get("start") or {}
    if start.get("dateTime"):
        try:
            return datetime.fromisoformat(start["dateTime"]).astimezone()
        except ValueError:
            return None
    if start.get("date"):  # 終日イベント
        try:
            return datetime.strptime(start["date"], "%Y-%m-%d").astimezone()
        except ValueError:
            return None
    return None


def format_event(event: dict) -> str:
    start = event.get("start") or {}
    if start.get("dateTime"):
        dt = event_start(event)
        when = dt.strftime("%H:%M") if dt else "??:??"
    else:
        when = "終日"
    title = event.get("summary") or "(無題の予定)"
    location = f" @{event['location']}" if event.get("location") else ""
    return f"{when} {title}{location}"


def to_rfc3339(local_str: str) -> str:
    """"YYYY-MM-DD HH:MM"(ローカル時刻)を RFC3339 に変換"""
    dt = datetime.strptime(local_str.replace("T", " ")[:16], TIME_FMT)
    return dt.astimezone().isoformat()


class GoogleWorkspacePlugin(PluginBase):
    async def on_load(self):
        self.client = httpx.AsyncClient(timeout=20.0)

    async def on_unload(self):
        await self.client.aclose()

    # --- 認証 ---

    async def _access_token(self, force_refresh: bool = False) -> str:
        token = await self.oauth.load("google")
        if token is None:
            raise RuntimeError(
                "Googleと未連携です。Web UIの📊タブから「Googleと連携」を実行してください"
            )
        expires_at = token.get("expires_at")
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expiring = expires_at is not None and expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60)

        if (force_refresh or expiring) and token.get("refresh_token"):
            token = await self._refresh(token["refresh_token"])
        return token["access_token"]

    async def _refresh(self, refresh_token: str) -> dict:
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        resp = await self.client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Googleトークンの更新に失敗(再連携が必要かも): {resp.text[:200]}")
        data = resp.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
        await self.oauth.save(
            "google", access_token=data["access_token"], expires_at=expires_at
        )
        return {"access_token": data["access_token"], "refresh_token": refresh_token}

    async def _get(self, url: str, params: dict | None = None) -> dict:
        token = await self._access_token()
        resp = await self.client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401:  # 失効していたら1回だけリフレッシュして再試行
            token = await self._access_token(force_refresh=True)
            resp = await self.client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            raise RuntimeError(f"Google API エラー HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _post(self, url: str, body: dict) -> dict:
        token = await self._access_token()
        resp = await self.client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            raise RuntimeError(f"Google API エラー HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # --- Calendar ---

    async def _fetch_events(self, time_min: datetime, time_max: datetime) -> list[dict]:
        data = await self._get(
            f"{CAL_BASE}/calendars/primary/events",
            params={
                "timeMin": time_min.astimezone().isoformat(),
                "timeMax": time_max.astimezone().isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 20,
            },
        )
        return data.get("items") or []

    @tool(description="Googleカレンダーの予定を取得する。days=1 で今日、days=7 で1週間分")
    async def get_events(self, days: int = 1) -> list:
        now = datetime.now().astimezone()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = await self._fetch_events(start_of_day, start_of_day + timedelta(days=max(1, int(days))))
        result = []
        for e in events:
            dt = event_start(e)
            result.append(
                {
                    "date": dt.strftime("%Y-%m-%d") if dt else "",
                    "time": format_event(e),
                    "title": e.get("summary") or "(無題の予定)",
                }
            )
        return result

    @tool(
        description=(
            "Googleカレンダーに予定を作成する。start / end は 'YYYY-MM-DD HH:MM' 形式。"
            "重要: 実行前に必ずタイトル・日時をユーザーに提示して確認を取ってから呼ぶこと"
        ),
        requires_confirmation=True,
    )
    async def create_event(self, title: str, start: str, end: str, description: str = "") -> dict:
        try:
            body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": to_rfc3339(start)},
                "end": {"dateTime": to_rfc3339(end)},
            }
        except ValueError:
            return {"error": "日時の形式が不正です(YYYY-MM-DD HH:MM で指定)"}
        created = await self._post(f"{CAL_BASE}/calendars/primary/events", body)
        return {"created": {"title": title, "start": start, "end": end, "url": created.get("htmlLink")}}

    # --- Gmail ---

    async def _fetch_mails(self, query: str, max_results: int) -> list[dict]:
        data = await self._get(
            f"{GMAIL_BASE}/users/me/messages",
            params={"q": query, "maxResults": max(1, min(int(max_results), 10))},
        )
        mails = []
        for ref in data.get("messages") or []:
            msg = await self._get(
                f"{GMAIL_BASE}/users/me/messages/{ref['id']}",
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            mails.append(extract_mail_headers(msg))
        return mails

    @tool(description="Gmailをクエリで検索する(Gmailの検索演算子が使える。例: 'from:amazon 請求')")
    async def search_emails(self, query: str, max_results: int = 5) -> list:
        return await self._fetch_mails(query, max_results)

    @tool(description="未読メールの一覧(送信元・件名・冒頭)を取得する")
    async def get_unread_summary(self, max_results: int = 5) -> list:
        return await self._fetch_mails("is:unread", max_results)

    # --- Job ---

    @job(cron=lambda self: daily_cron(self.config.get("briefing_time") or "07:30"))
    async def morning_briefing(self) -> str:
        if not self.config.get("briefing_enabled"):
            return "briefing_enabled=false(スキップ)"
        if await self.oauth.load("google") is None:
            return "Google未連携(スキップ)"

        now = datetime.now().astimezone()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = await self._fetch_events(start_of_day, start_of_day + timedelta(days=1))
        unread = await self._fetch_mails("is:unread newer_than:2d", 5)

        lines = [f"📅 今日の予定({len(events)}件)"]
        lines += [f"・{format_event(e)}" for e in events] or ["・予定なし"]
        lines.append("")
        lines.append(f"📧 未読メール({len(unread)}件)")
        lines += [f"・{m['subject']} — {m['from']}" for m in unread] or ["・未読なし"]

        await self.notify(title="🌅 おはようブリーフィング", body="\n".join(lines), channel="daily")
        return f"予定{len(events)}件 / 未読{len(unread)}件"

    @job(cron="*/5 * * * *")
    async def mail_watch(self) -> str:
        if not self.config.get("mail_watch_enabled"):
            return "mail_watch_enabled=false(スキップ)"
        if await self.oauth.load("google") is None:
            return "Google未連携(スキップ)"

        notified: list[str] = await self.storage.get(NOTIFIED_MAIL_KEY, [])
        mails = await self._fetch_mails("is:unread newer_than:1d", 10)
        new_important = [
            m for m in mails
            if m["id"] not in notified
            and is_important_mail(
                m, self.config.get("important_senders"), self.config.get("important_keywords")
            )
        ]
        for m in new_important:
            await self.notify(
                title=f"📧 重要メール: {m['subject']}",
                body=f"From: {m['from']}\n{m['snippet']}",
                channel="important",
            )
            notified.append(m["id"])
        await self.storage.set(NOTIFIED_MAIL_KEY, notified[-500:])
        return f"重要{len(new_important)}件通知"

    @job(cron="*/15 * * * *")
    async def event_reminder(self) -> str:
        if not self.config.get("event_reminder_enabled"):
            return "event_reminder_enabled=false(スキップ)"
        if await self.oauth.load("google") is None:
            return "Google未連携(スキップ)"

        reminded: list[str] = await self.storage.get(REMINDED_EVENT_KEY, [])
        now = datetime.now().astimezone()
        events = await self._fetch_events(now, now + timedelta(minutes=30))
        count = 0
        for e in events:
            key = f"{e.get('id')}:{(e.get('start') or {}).get('dateTime', '')}"
            dt = event_start(e)
            if key in reminded or dt is None or dt < now:
                continue
            await self.notify(
                title="🔔 まもなく予定",
                body=f"{format_event(e)}({dt.strftime('%H:%M')}開始)",
                channel="important",
            )
            reminded.append(key)
            count += 1
        await self.storage.set(REMINDED_EVENT_KEY, reminded[-200:])
        return f"{count}件リマインド"

    # --- ダッシュボードカード ---

    async def dashboard(self) -> dict:
        if await self.oauth.load("google") is None:
            return {
                "title": "📅 今日の予定",
                "items": [],
                "footer": "Google未連携(下の「Googleと連携」から接続)",
            }
        now = datetime.now().astimezone()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = await self._fetch_events(start_of_day, start_of_day + timedelta(days=1))
        unread = await self._get(f"{GMAIL_BASE}/users/me/labels/UNREAD")
        return {
            "title": "📅 今日の予定",
            "items": [{"text": format_event(e), "url": e.get("htmlLink")} for e in events[:6]],
            "footer": f"📧 未読メール {unread.get('messagesUnread', '?')}件",
        }
