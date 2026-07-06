"""プラグイン管理 REST API(docs/01 FR-12 管理画面のバックエンド)"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from shion.db.models import JobLog
from shion.plugins.loader import PluginInfo, PluginManager

router = APIRouter()


def _manager(request: Request) -> PluginManager:
    return request.app.state.plugin_manager


async def _serialize(manager: PluginManager, info: PluginInfo) -> dict:
    return {
        "name": info.name,
        "display_name": info.display_name,
        "version": info.version,
        "description": info.description,
        "author": info.author,
        "enabled": info.enabled,
        "status": info.status,
        "error": info.error,
        "config_schema": info.config_schema,
        "config": await manager.get_config(info.name),
        "tools": info.tool_names,
        "jobs": info.jobs,
    }


@router.get("/plugins")
async def list_plugins(request: Request):
    manager = _manager(request)
    return [await _serialize(manager, info) for info in manager.plugins.values()]


class EnabledBody(BaseModel):
    enabled: bool


@router.put("/plugins/{name}")
async def set_enabled(name: str, body: EnabledBody, request: Request):
    manager = _manager(request)
    try:
        info = await manager.set_enabled(name, body.enabled)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await _serialize(manager, info)


class ConfigBody(BaseModel):
    config: dict


@router.put("/plugins/{name}/config")
async def update_config(name: str, body: ConfigBody, request: Request):
    manager = _manager(request)
    try:
        info = await manager.update_config(name, body.config)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await _serialize(manager, info)


@router.post("/plugins/{name}/reload")
async def reload_plugin(name: str, request: Request):
    manager = _manager(request)
    try:
        info = await manager.reload(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await _serialize(manager, info)


@router.post("/plugins/{name}/jobs/{job_name}/run")
async def run_job(name: str, job_name: str, request: Request):
    try:
        await request.app.state.scheduler.run_now(name, job_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}


@router.get("/plugins/{name}/logs")
async def job_logs(name: str, request: Request, limit: int = 20):
    async with request.app.state.sessions() as db:
        rows = (
            await db.execute(
                select(JobLog)
                .where(JobLog.plugin_name == name)
                .order_by(JobLog.id.desc())
                .limit(min(limit, 100))
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "job_name": r.job_name,
            "status": r.status,
            "detail": r.detail,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]
