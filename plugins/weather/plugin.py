"""天気予報プラグイン(プラグインシステムのリファレンス実装)。

- Tool: get_weather … 会話中に紫桜が自律的に呼び出す
- Job:  morning_forecast … 毎朝の天気通知(config の notify_time)
データソースは Open-Meteo(https://open-meteo.com/)。APIキー不要。
"""

from __future__ import annotations

import httpx

from shion.plugins import PluginBase, daily_cron, job, tool

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → 日本語(主要コードのみ)
WMO_JA = {
    0: "快晴", 1: "晴れ", 2: "薄曇り", 3: "曇り",
    45: "霧", 48: "霧(着氷性)",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨",
    61: "小雨", 63: "雨", 65: "大雨",
    66: "みぞれ", 67: "強いみぞれ",
    71: "小雪", 73: "雪", 75: "大雪", 77: "霧雪",
    80: "にわか雨", 81: "にわか雨", 82: "激しいにわか雨",
    85: "にわか雪", 86: "強いにわか雪",
    95: "雷雨", 96: "雷雨(ひょう)", 99: "激しい雷雨(ひょう)",
}


class WeatherPlugin(PluginBase):
    async def on_load(self) -> None:
        self._client = httpx.AsyncClient(timeout=20)

    async def on_unload(self) -> None:
        await self._client.aclose()

    @tool(
        description=(
            "指定した地域の今日から3日分の天気予報(天気・最高/最低気温・降水確率)を取得する。"
            "地名は日本語でも英語でもよい。地名を省略するとユーザーのデフォルト地域を使う。"
        )
    )
    async def get_weather(self, location: str = "") -> dict:
        location = location or self.config.get("location") or "Tokyo"
        geo = await self._geocode(location)
        resp = await self._client.get(
            FORECAST_URL,
            params={
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 3,
            },
        )
        resp.raise_for_status()
        daily = resp.json()["daily"]
        days = [
            {
                "date": daily["time"][i],
                "weather": WMO_JA.get(daily["weather_code"][i], f"code {daily['weather_code'][i]}"),
                "temp_max": daily["temperature_2m_max"][i],
                "temp_min": daily["temperature_2m_min"][i],
                "precipitation_prob": daily["precipitation_probability_max"][i],
            }
            for i in range(len(daily["time"]))
        ]
        return {"location": geo["name"], "days": days}

    @job(cron=lambda self: daily_cron(self.config.get("notify_time") or "07:00"))
    async def morning_forecast(self) -> None:
        if not self.config.get("morning_notify", True):
            return
        forecast = await self.get_weather()
        today = forecast["days"][0]
        body = (
            f"{forecast['location']}の今日の天気は「{today['weather']}」だよ。"
            f"最高 {today['temp_max']}℃ / 最低 {today['temp_min']}℃、"
            f"降水確率は {today['precipitation_prob']}%。"
        )
        if (today["precipitation_prob"] or 0) >= 50:
            body += " 傘を忘れずにね☂️"
        await self.notify(title="今日の天気", body=body, channel="daily")

    async def _geocode(self, location: str) -> dict:
        resp = await self._client.get(
            GEOCODING_URL,
            params={"name": location, "count": 1, "language": "ja", "format": "json"},
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            raise ValueError(f"地名「{location}」が見つかりませんでした")
        r = results[0]
        return {"name": r["name"], "latitude": r["latitude"], "longitude": r["longitude"]}
