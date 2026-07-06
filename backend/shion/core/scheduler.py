"""Scheduler: プラグインJobのcron実行と実行ログ記録(docs/02, docs/03)"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.db.models import JobLog

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sessions = session_factory
        self._scheduler = AsyncIOScheduler()
        self._runners: dict[str, Callable[[], Awaitable[None]]] = {}

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def register(
        self,
        plugin_name: str,
        job_name: str,
        cron: str,
        func: Callable[[], Awaitable[None]],
    ) -> None:
        key = f"{plugin_name}.{job_name}"
        runner = self._make_runner(plugin_name, job_name, func)
        self._runners[key] = runner
        self._scheduler.add_job(
            runner,
            CronTrigger.from_crontab(cron),
            id=key,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("ジョブ登録: %s (cron=%s)", key, cron)

    def unregister_plugin(self, plugin_name: str) -> None:
        prefix = f"{plugin_name}."
        for key in [k for k in self._runners if k.startswith(prefix)]:
            self._runners.pop(key, None)
            if self._scheduler.get_job(key):
                self._scheduler.remove_job(key)

    async def run_now(self, plugin_name: str, job_name: str) -> None:
        """管理画面からの手動実行"""
        runner = self._runners.get(f"{plugin_name}.{job_name}")
        if runner is None:
            raise KeyError(f"ジョブ {plugin_name}.{job_name} は登録されていません")
        await runner()

    def _make_runner(
        self, plugin_name: str, job_name: str, func: Callable[[], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        async def runner() -> None:
            async with self._sessions() as db:
                log = JobLog(plugin_name=plugin_name, job_name=job_name, status="running")
                db.add(log)
                await db.commit()
                log_id = log.id
            try:
                await func()
                status, detail = "success", None
            except Exception as e:  # noqa: BLE001 - Job失敗はログに記録して継続(docs/03 障害隔離)
                logger.exception("ジョブ %s.%s が失敗", plugin_name, job_name)
                status, detail = "error", str(e)[:1000]
            async with self._sessions() as db:
                log = await db.get(JobLog, log_id)
                if log:
                    log.status = status
                    log.detail = detail
                    log.finished_at = datetime.now(timezone.utc)
                    await db.commit()

        return runner
