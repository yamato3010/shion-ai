"""プロアクティブ会話プラグイン(docs/09 フェーズ4)

- bedtime: 就寝前の声かけ(毎日、設定時刻)
- idle_check: しばらく会話がないときの様子うかがい(30分ごとに判定)

発話そのものはコアに任せる(self.speak に演出指示を渡すだけ)。
最終会話時刻は Event Bus の message.received を購読して記録する。
"""

from __future__ import annotations

from datetime import datetime

from shion.plugins import PluginBase, daily_cron, job

LAST_ACTIVITY_KEY = "last_activity"
LAST_IDLE_CALL_KEY = "last_idle_call"
TIME_FMT = "%Y-%m-%d %H:%M:%S"

IDLE_INSTRUCTION = (
    "ユーザーからしばらく話しかけられていない。会話の文脈や時間帯に合った、"
    "押し付けがましくない軽い声かけや雑談をする(様子うかがい、天気や時間帯の話題など)"
)
BEDTIME_INSTRUCTION = (
    "そろそろ就寝時刻。夜更かししないよう、優しく寝る準備を促す。"
    "今日も一日おつかれさま、という労いを添える"
)


def _parse_hhmm(value: str, default: str) -> tuple[int, int]:
    raw = (value or default).strip()
    hour, _, minute = raw.partition(":")
    try:
        return int(hour), int(minute or 0)
    except ValueError:
        hour, _, minute = default.partition(":")
        return int(hour), int(minute)


def in_active_window(now: datetime, start: str, end: str) -> bool:
    """声かけしてよい時間帯か。start > end の場合は日をまたぐ窓として扱う"""
    start_h, start_m = _parse_hhmm(start, "09:00")
    end_h, end_m = _parse_hhmm(end, "23:00")
    minutes = now.hour * 60 + now.minute
    start_min = start_h * 60 + start_m
    end_min = end_h * 60 + end_m
    if start_min <= end_min:
        return start_min <= minutes <= end_min
    return minutes >= start_min or minutes <= end_min


def should_idle_call(
    now: datetime,
    last_activity: datetime | None,
    last_call: datetime | None,
    idle_hours: int,
) -> bool:
    """アイドル声かけの判定。前回の声かけからも idle_hours 空ける(連投防止)"""
    if idle_hours <= 0 or last_activity is None:
        return False  # 一度も会話がないうちは声をかけない
    idle_sec = idle_hours * 3600
    if (now - last_activity).total_seconds() < idle_sec:
        return False
    if last_call is not None and (now - last_call).total_seconds() < idle_sec:
        return False
    return True


class ProactivePlugin(PluginBase):
    async def on_load(self) -> None:
        self.events.subscribe("message.received", self._on_message)

    async def on_unload(self) -> None:
        self.events.unsubscribe("message.received", self._on_message)

    async def _on_message(self, payload: dict) -> None:
        if payload.get("interface") == "proactive":
            return
        await self.storage.set(LAST_ACTIVITY_KEY, datetime.now().strftime(TIME_FMT))

    async def _get_time(self, key: str) -> datetime | None:
        raw = await self.storage.get(key)
        return datetime.strptime(raw, TIME_FMT) if raw else None

    @job(cron=lambda self: daily_cron(self.config.get("bedtime") or "23:30"))
    async def bedtime(self) -> str:
        if not (self.config.get("bedtime") or "").strip():
            return "bedtime未設定(スキップ)"
        await self.speak(BEDTIME_INSTRUCTION)
        return "就寝の声かけ"

    @job(cron="*/30 * * * *")
    async def idle_check(self) -> str:
        now = datetime.now()
        if not in_active_window(
            now, self.config.get("active_start") or "09:00", self.config.get("active_end") or "23:00"
        ):
            return "時間帯外(スキップ)"
        last_activity = await self._get_time(LAST_ACTIVITY_KEY)
        last_call = await self._get_time(LAST_IDLE_CALL_KEY)
        if not should_idle_call(now, last_activity, last_call, int(self.config.get("idle_hours") or 0)):
            return "条件未達(スキップ)"
        await self.speak(IDLE_INSTRUCTION)
        await self.storage.set(LAST_IDLE_CALL_KEY, now.strftime(TIME_FMT))
        return "様子うかがいの声かけ"
