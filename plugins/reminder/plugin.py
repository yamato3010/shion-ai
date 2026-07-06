"""リマインダープラグイン(docs/09 フェーズ2)

会話中に紫桜がツールで登録し(「明日9時に会議をリマインドして」)、
毎分のジョブで期限を迎えたものを通知する。時刻は "YYYY-MM-DD HH:MM" の
ローカル時刻。相対表現(「明日」「3時間後」)は LLM が現在日時から絶対時刻に
変換してツールへ渡す(システムプロンプトに現在日時が入っているため可能)。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from shion.plugins import PluginBase, command, job, tool

STORAGE_KEY = "items"
TIME_FMT = "%Y-%m-%d %H:%M"


def parse_when(when: str) -> datetime:
    """"YYYY-MM-DD HH:MM" / "HH:MM"(今日、過ぎていれば明日)をdatetimeにする"""
    when = when.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", when):
        hour, minute = map(int, when.split(":"))
        candidate = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= datetime.now():
            candidate += timedelta(days=1)
        return candidate
    return datetime.strptime(when.replace("T", " ")[:16], TIME_FMT)


class ReminderPlugin(PluginBase):
    async def _items(self) -> list[dict]:
        return await self.storage.get(STORAGE_KEY, [])

    async def _save(self, items: list[dict]) -> None:
        await self.storage.set(STORAGE_KEY, items)

    # --- Tools(会話中に紫桜が使う) ---

    @tool(
        description=(
            "リマインダーを登録する。when は 'YYYY-MM-DD HH:MM' 形式のローカル時刻。"
            "「明日」「3時間後」などの相対表現は現在日時から計算して絶対時刻で渡すこと"
        )
    )
    async def add_reminder(self, content: str, when: str) -> dict:
        try:
            fire_at = parse_when(when)
        except ValueError:
            return {"error": f"時刻の形式が不正です: {when}(YYYY-MM-DD HH:MM で指定)"}
        if fire_at <= datetime.now():
            return {"error": f"過去の時刻は指定できません: {fire_at.strftime(TIME_FMT)}"}
        items = await self._items()
        reminder = {
            "id": max((i["id"] for i in items), default=0) + 1,
            "content": content.strip(),
            "fire_at": fire_at.strftime(TIME_FMT),
            "status": "pending",
        }
        items.append(reminder)
        await self._save(items)
        return {"registered": reminder}

    @tool(description="登録済みの未完了リマインダーの一覧を返す")
    async def list_reminders(self) -> list:
        return [i for i in await self._items() if i["status"] == "pending"]

    @tool(description="指定IDのリマインダーを取り消す")
    async def cancel_reminder(self, reminder_id: int) -> dict:
        items = await self._items()
        for item in items:
            if item["id"] == reminder_id and item["status"] == "pending":
                item["status"] = "cancelled"
                await self._save(items)
                return {"cancelled": item}
        return {"error": f"未完了のリマインダー id={reminder_id} が見つかりません"}

    # --- Job: 毎分、期限を迎えたものを通知する ---

    @job(cron="* * * * *")
    async def check_due(self) -> None:
        now = datetime.now()
        items = await self._items()
        fired = False
        for item in items:
            if item["status"] != "pending":
                continue
            if datetime.strptime(item["fire_at"], TIME_FMT) <= now:
                await self.notify(
                    title="⏰ リマインダー",
                    body=item["content"],
                    channel=self.config.get("notify_channel") or "important",
                )
                item["status"] = "fired"
                fired = True
        if fired:
            await self._save(items)

    # --- Command: Discord の /remind ---

    @command(name="remind", description="リマインダー登録(例: 21:30 お風呂)。空なら一覧を表示")
    async def remind_command(self, text: str = "") -> str:
        text = text.strip()
        if not text:
            pending = [i for i in await self._items() if i["status"] == "pending"]
            if not pending:
                return "未完了のリマインダーはないよ!"
            return "\n".join(f"[{i['id']}] {i['fire_at']} {i['content']}" for i in pending)

        match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}|\d{1,2}:\d{2})\s+(.+)$", text)
        if not match:
            return "書式: `/remind HH:MM 内容` または `/remind YYYY-MM-DD HH:MM 内容`"
        result = await self.add_reminder(content=match.group(2), when=match.group(1))
        if "error" in result:
            return f"⚠ {result['error']}"
        r = result["registered"]
        return f"⏰ {r['fire_at']} に「{r['content']}」をリマインドするね!"
