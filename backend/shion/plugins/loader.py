"""プラグインローダ / PluginManager(docs/03 §3)

- plugins/ 直下を走査して plugin.yaml を読む
- enabled なプラグインを動的import・インスタンス化
- @tool → LLMツールとして登録(型ヒントからJSON Schemaを自動生成)
- @job → Scheduler にcron登録
- プラグインの例外はコアを落とさない(障害隔離)
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shion.core.events import EventBus
from shion.core.scheduler import Scheduler
from shion.db.models import PluginSetting
from shion.llm import LLMRouter, ToolSpec
from shion.plugins.base import (
    ATTR_COMMAND,
    ATTR_JOB,
    ATTR_TOOL,
    PluginBase,
    PluginContext,
    PluginStorage,
)

logger = logging.getLogger(__name__)

SUPPORTED_API_VERSION = 1
TOOL_TIMEOUT_SEC = 30

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def build_tool_parameters(fn: Callable) -> dict:
    """メソッドシグネチャの型ヒントから function calling 用 JSON Schema を生成"""
    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        if name == "self":
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        json_type = _TYPE_MAP.get(annotation, "string")
        prop: dict[str, Any] = {"type": json_type}
        if json_type == "array":
            prop["items"] = {"type": "string"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default
        properties[name] = prop
    return {"type": "object", "properties": properties, "required": required}


@dataclass
class RegisteredTool:
    plugin_name: str
    spec: ToolSpec
    fn: Callable
    requires_confirmation: bool = False


@dataclass
class RegisteredCommand:
    plugin_name: str
    name: str
    description: str
    fn: Callable


@dataclass
class PluginInfo:
    name: str
    path: Path
    display_name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    api_version: int = 1
    config_schema: dict = field(default_factory=dict)
    enabled: bool = False
    status: str = "disabled"  # disabled | loaded | error
    error: str | None = None
    instance: PluginBase | None = None
    jobs: list[dict] = field(default_factory=list)  # [{name, cron}]
    commands: list[dict] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)


class PluginManager:
    def __init__(
        self,
        plugins_dir: Path,
        session_factory: async_sessionmaker,
        llm: LLMRouter,
        events: EventBus,
        scheduler: Scheduler,
        oauth_store=None,
    ) -> None:
        self._dir = plugins_dir
        self._sessions = session_factory
        self._llm = llm
        self._events = events
        self._scheduler = scheduler
        self._oauth = oauth_store
        self.plugins: dict[str, PluginInfo] = {}
        self._tools: dict[str, RegisteredTool] = {}
        self._commands: dict[str, RegisteredCommand] = {}

    # --- 起動処理 ---

    async def setup(self) -> None:
        self.discover()
        await self._sync_settings()
        for info in self.plugins.values():
            if info.enabled:
                await self.load(info.name)

    def discover(self) -> None:
        if not self._dir.exists():
            return
        for path in sorted(self._dir.iterdir()):
            manifest = path / "plugin.yaml"
            if not path.is_dir() or not manifest.exists():
                continue
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                name = data.get("name") or path.name
                info = PluginInfo(
                    name=name,
                    path=path,
                    display_name=data.get("display_name", name),
                    version=str(data.get("version", "0.0.0")),
                    description=data.get("description", ""),
                    author=data.get("author", ""),
                    api_version=int(data.get("api_version", 1)),
                    config_schema=data.get("config_schema") or {},
                )
                if info.api_version > SUPPORTED_API_VERSION:
                    info.status = "error"
                    info.error = f"api_version {info.api_version} は未対応(コアは {SUPPORTED_API_VERSION})"
                self.plugins[name] = info
            except Exception as e:  # noqa: BLE001
                logger.error("プラグイン %s のマニフェスト読み込みに失敗: %s", path.name, e)

    async def _sync_settings(self) -> None:
        """DBの有効/無効・設定と突き合わせる。新規発見分は enabled=false で登録"""
        async with self._sessions() as db:
            rows = {
                r.plugin_name: r
                for r in (await db.execute(select(PluginSetting))).scalars().all()
            }
            for info in self.plugins.values():
                row = rows.get(info.name)
                if row is None:
                    db.add(PluginSetting(plugin_name=info.name, enabled=False))
                else:
                    info.enabled = row.enabled
            await db.commit()

    # --- ロード / アンロード ---

    async def load(self, name: str) -> PluginInfo:
        info = self._require(name)
        if info.status == "loaded":
            return info
        try:
            config = await self._resolve_config(info)
            ctx = PluginContext(
                name=info.name,
                config=config,
                llm=self._llm,
                events=self._events,
                storage=PluginStorage(self._sessions, info.name),
                oauth=self._oauth,
            )
            instance = self._instantiate(info, ctx)
            await instance.on_load()
            info.instance = instance
            self._register_capabilities(info, instance)
            info.status = "loaded"
            info.error = None
            logger.info(
                "プラグイン %s をロード(tools=%s, jobs=%s)",
                info.name,
                info.tool_names,
                [j["name"] for j in info.jobs],
            )
        except Exception as e:  # noqa: BLE001 - ロード失敗はerror状態にしてコアは継続
            logger.exception("プラグイン %s のロードに失敗", name)
            info.status = "error"
            info.error = str(e)
            info.instance = None
        return info

    async def unload(self, name: str) -> PluginInfo:
        info = self._require(name)
        self._scheduler.unregister_plugin(name)
        self._tools = {k: v for k, v in self._tools.items() if v.plugin_name != name}
        self._commands = {k: v for k, v in self._commands.items() if v.plugin_name != name}
        info.jobs = []
        info.commands = []
        info.tool_names = []
        if info.instance is not None:
            try:
                await info.instance.on_unload()
            except Exception:  # noqa: BLE001
                logger.exception("プラグイン %s の on_unload で例外", name)
            info.instance = None
        sys.modules.pop(self._module_name(name), None)
        info.status = "disabled" if info.error is None else "error"
        return info

    async def reload(self, name: str) -> PluginInfo:
        await self.unload(name)
        info = self._require(name)
        info.error = None
        if info.enabled:
            return await self.load(name)
        info.status = "disabled"
        return info

    async def set_enabled(self, name: str, enabled: bool) -> PluginInfo:
        info = self._require(name)
        info.enabled = enabled
        async with self._sessions() as db:
            row = await db.get(PluginSetting, name)
            if row is None:
                row = PluginSetting(plugin_name=name)
                db.add(row)
            row.enabled = enabled
            await db.commit()
        if enabled:
            info.error = None
            return await self.load(name)
        return await self.unload(name)

    async def update_config(self, name: str, config: dict) -> PluginInfo:
        info = self._require(name)
        known_keys = set(info.config_schema.keys())
        clean = {k: v for k, v in config.items() if k in known_keys}
        async with self._sessions() as db:
            row = await db.get(PluginSetting, name)
            if row is None:
                row = PluginSetting(plugin_name=name, enabled=info.enabled)
                db.add(row)
            row.config_json = json.dumps(clean, ensure_ascii=False)
            await db.commit()
        # 設定変更を反映するためリロード(cron等も再評価される)
        return await self.reload(name)

    async def get_config(self, name: str) -> dict:
        return await self._resolve_config(self._require(name))

    # --- ツール実行(Agentから利用) ---

    def get_toolspecs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def execute_tool(self, tool_name: str, args: dict) -> Any:
        registered = self._tools.get(tool_name)
        if registered is None:
            raise KeyError(f"ツール '{tool_name}' は存在しません")
        return await asyncio.wait_for(registered.fn(**args), timeout=TOOL_TIMEOUT_SEC)

    # --- ダッシュボードカード収集(📊画面から利用) ---

    async def get_dashboard_cards(self) -> list[dict]:
        """dashboard() を実装しているロード済みプラグインからカードを集める"""
        cards: list[dict] = []
        for info in self.plugins.values():
            instance = info.instance
            if instance is None:
                continue
            if type(instance).dashboard is PluginBase.dashboard:
                continue  # オーバーライドしていない
            try:
                card = await asyncio.wait_for(instance.dashboard(), timeout=TOOL_TIMEOUT_SEC)
            except Exception as e:  # noqa: BLE001 - 1枚の失敗で画面全体を壊さない
                logger.exception("プラグイン %s の dashboard() が失敗", info.name)
                card = {"title": info.display_name, "items": [], "footer": f"⚠ 取得失敗: {e}"}
            if card:
                card["plugin"] = info.name
                card.setdefault("title", info.display_name)
                cards.append(card)
        return cards

    # --- コマンド実行(Discordアダプタから利用) ---

    def get_commands(self) -> list[RegisteredCommand]:
        return list(self._commands.values())

    async def execute_command(self, command_name: str, text: str = "") -> Any:
        registered = self._commands.get(command_name)
        if registered is None:
            raise KeyError(f"コマンド '{command_name}' は存在しません")
        # 引数を1つ以上取るコマンドには入力テキストをそのまま渡す
        params = inspect.signature(registered.fn).parameters
        if params:
            coro = registered.fn(text)
        else:
            coro = registered.fn()
        return await asyncio.wait_for(coro, timeout=TOOL_TIMEOUT_SEC)

    # --- 内部処理 ---

    def _require(self, name: str) -> PluginInfo:
        if name not in self.plugins:
            raise KeyError(f"プラグイン '{name}' が見つかりません")
        return self.plugins[name]

    def _module_name(self, name: str) -> str:
        return f"shion_plugins.{name}"

    def _instantiate(self, info: PluginInfo, ctx: PluginContext) -> PluginBase:
        entry = info.path / "plugin.py"
        if not entry.exists():
            raise FileNotFoundError(f"{entry} がありません")
        module_name = self._module_name(info.name)
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, entry)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, PluginBase)
                and obj is not PluginBase
                and obj.__module__ == module_name
            ):
                return obj(ctx)
        raise TypeError(f"{entry} に PluginBase のサブクラスが見つかりません")

    async def _resolve_config(self, info: PluginInfo) -> dict:
        """config_schema のデフォルト値に、DB保存の上書き設定をマージ"""
        config = {k: v.get("default") for k, v in info.config_schema.items()}
        async with self._sessions() as db:
            row = await db.get(PluginSetting, info.name)
        if row and row.config_json:
            try:
                config.update(json.loads(row.config_json))
            except json.JSONDecodeError:
                logger.warning("プラグイン %s の保存設定が壊れています", info.name)
        return config

    def _register_capabilities(self, info: PluginInfo, instance: PluginBase) -> None:
        info.jobs = []
        info.commands = []
        info.tool_names = []
        for attr_name, member in inspect.getmembers(instance, predicate=inspect.iscoroutinefunction):
            fn = getattr(type(instance), attr_name, None)
            if fn is None:
                continue
            if hasattr(fn, ATTR_TOOL):
                meta = getattr(fn, ATTR_TOOL)
                spec = ToolSpec(
                    name=attr_name,
                    description=meta["description"],
                    parameters=build_tool_parameters(fn),
                )
                if attr_name in self._tools:
                    raise ValueError(
                        f"ツール名 '{attr_name}' が {self._tools[attr_name].plugin_name} と重複しています"
                    )
                self._tools[attr_name] = RegisteredTool(
                    plugin_name=info.name,
                    spec=spec,
                    fn=member,
                    requires_confirmation=meta["requires_confirmation"],
                )
                info.tool_names.append(attr_name)
            if hasattr(fn, ATTR_JOB):
                cron_spec = getattr(fn, ATTR_JOB)["cron"]
                cron = cron_spec(instance) if callable(cron_spec) else cron_spec
                self._scheduler.register(info.name, attr_name, cron, member)
                info.jobs.append({"name": attr_name, "cron": cron})
            if hasattr(fn, ATTR_COMMAND):
                meta = getattr(fn, ATTR_COMMAND)
                if meta["name"] in self._commands:
                    raise ValueError(
                        f"コマンド名 '{meta['name']}' が "
                        f"{self._commands[meta['name']].plugin_name} と重複しています"
                    )
                self._commands[meta["name"]] = RegisteredCommand(
                    plugin_name=info.name,
                    name=meta["name"],
                    description=meta["description"],
                    fn=member,
                )
                info.commands.append(meta)
