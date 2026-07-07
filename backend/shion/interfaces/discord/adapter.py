"""Discord Bot アダプタ(docs/05 §2)

- DM: オーナーの全メッセージを紫桜への発話として扱う
- サーバーチャンネル: メンションされたときのみ反応
- 応答はストリーミング途中経過をメッセージ編集で反映(1秒間隔スロットル)
- スラッシュコマンド: コアの /new /status + プラグインの @command を自動登録
- 通知: NotificationRouter から send_notification() が呼ばれ、オーナーへDM(Embed)

会話セッションは Web と同一DBを共有する。Discord側は「現在の会話ID」を
KVに永続化して継ぎ、/new でリセットする(Web UIからも同じ会話を閲覧・継続できる)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import discord
from discord import app_commands

from shion.interfaces.discord.format import (
    clip_streaming,
    emotion_prefix,
    split_message,
)
from shion.plugins.base import PluginStorage

logger = logging.getLogger(__name__)

EDIT_INTERVAL_SEC = 1.0  # 編集レート制限対策(docs/05 §2.4)
CONVERSATION_KEY = "conversation_id"


class DiscordAdapter(discord.Client):
    def __init__(
        self,
        agent,
        plugin_manager,
        llm_router,
        memory,
        session_factory,
        config: dict | None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._agent = agent
        self._plugins = plugin_manager
        self._router = llm_router
        self._memory = memory
        self._config = config or {}
        # 会話ポインタの永続化。plugin_kv の名前空間を間借りする("_" 始まりはコア予約)
        self._kv = PluginStorage(session_factory, "_discord")
        self._tree = app_commands.CommandTree(self)
        self._started_at = time.time()

    # --- 設定 ---

    @property
    def owner_id(self) -> int | None:
        raw = str(self._config.get("owner_id") or "").strip()
        return int(raw) if raw.isdigit() else None

    # --- 起動・停止 ---

    async def run_forever(self, token: str) -> None:
        try:
            await self.start(token)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Bot起動失敗でコアは落とさない
            logger.exception("Discord Bot の起動に失敗(トークン・intent設定を確認)")

    async def setup_hook(self) -> None:
        self._register_core_commands()
        for cmd in self._plugins.get_commands():
            self._register_plugin_command(cmd.name, cmd.description)
        guild_id = str(self._config.get("command_guild_id") or "").strip()
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self._tree.copy_global_to(guild=guild)
            await self._tree.sync(guild=guild)  # ギルド限定は即時反映
        else:
            await self._tree.sync()  # グローバルは反映に最大1時間かかる

    async def on_ready(self) -> None:
        logger.info("Discord Bot ログイン完了: %s (id=%s)", self.user, self.user.id)
        if self.owner_id is None:
            logger.warning("discord.owner_id が未設定。DMで案内を返します")

    # --- 対話 ---

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if message.guild is None:
            text = message.content.strip()
        elif self.user in message.mentions:
            text = (
                message.content.replace(f"<@{self.user.id}>", "")
                .replace(f"<@!{self.user.id}>", "")
                .strip()
            )
        else:
            return
        if not text:
            return

        if self.owner_id is None:
            await message.channel.send(
                "オーナーが未設定だよ。`config/config.yaml` の `discord.owner_id` に "
                f"`{message.author.id}` を設定して再起動してね。"
            )
            return
        if message.author.id != self.owner_id:
            return  # オーナー以外には反応しない(docs/08)

        try:
            await self._chat(message.channel, text)
        except Exception:  # noqa: BLE001
            logger.exception("Discordでの応答生成に失敗")
            await message.channel.send("⚠ ごめんね、応答の生成に失敗しちゃった……")

    async def _chat(self, channel, text: str) -> None:
        conversation_id = await self._kv.get(CONVERSATION_KEY)
        reply_msg: discord.Message | None = None
        buffer = ""
        emotion: str | None = None
        status = ""
        last_edit = 0.0

        async with channel.typing():
            async for ev in self._agent.stream_reply(conversation_id, text, interface="discord"):
                kind = ev["type"]
                if kind == "session":
                    await self._kv.set(CONVERSATION_KEY, ev["conversation_id"])
                elif kind == "chunk":
                    buffer += ev["text"]
                elif kind == "emotion":
                    emotion = ev["value"]
                elif kind == "tool_status":
                    status = f"🔧 `{ev['name']}` 実行中…" if ev["state"] == "running" else ""
                elif kind == "error":
                    buffer += f"\n⚠ {ev['message']}"

                display = "\n".join(p for p in (buffer.strip(), status) if p)
                if not display:
                    continue
                now = asyncio.get_running_loop().time()
                if reply_msg is None:
                    reply_msg = await channel.send(clip_streaming(display))
                    last_edit = now
                elif now - last_edit >= EDIT_INTERVAL_SEC:
                    await reply_msg.edit(content=clip_streaming(display))
                    last_edit = now

        parts = split_message(f"{emotion_prefix(emotion)} {buffer.strip()}")
        if reply_msg is None:
            reply_msg = await channel.send(parts[0])
        else:
            await reply_msg.edit(content=parts[0])
        for extra in parts[1:]:
            await channel.send(extra)

    # --- 通知(NotificationRouter から呼ばれる) ---

    async def send_notification(self, payload: dict) -> None:
        if self.owner_id is None:
            logger.warning("discord.owner_id 未設定のためDM通知をスキップ")
            return
        if not self.is_ready():
            logger.warning("Discord Bot 未接続のためDM通知をスキップ")
            return
        user = self.get_user(self.owner_id) or await self.fetch_user(self.owner_id)
        embed = discord.Embed(
            title=(payload.get("title") or "")[:256],
            description=(payload.get("body") or "")[:4000],
            url=payload.get("url") or None,
            color=0xB48AF0,  # 紫桜カラー
        )
        plugin = payload.get("plugin")
        if plugin:
            embed.set_footer(text=f"🌸 紫桜 / {plugin}")
        await user.send(embed=embed)

    async def send_proactive(self, text: str, emotion: str | None = None) -> None:
        """紫桜からの自発的発話をオーナーDMへ届ける(ProactiveSpeaker から呼ばれる)"""
        if self.owner_id is None or not self.is_ready():
            logger.debug("Discord未接続のためプロアクティブ発話をスキップ")
            return
        user = self.get_user(self.owner_id) or await self.fetch_user(self.owner_id)
        for part in split_message(f"{emotion_prefix(emotion)} {text}"):
            await user.send(part)

    # --- スラッシュコマンド ---

    def _register_core_commands(self) -> None:
        tree = self._tree
        adapter = self

        @tree.command(name="new", description="新しい会話を始める(文脈リセット)")
        async def new_command(interaction: discord.Interaction) -> None:
            if not await adapter._allow(interaction):
                return
            await adapter._kv.delete(CONVERSATION_KEY)
            await interaction.response.send_message("🌸 新しい会話を始めるね!")

        @tree.command(name="status", description="紫桜の稼働状態を表示")
        async def status_command(interaction: discord.Interaction) -> None:
            if not await adapter._allow(interaction):
                return
            uptime = int(time.time() - adapter._started_at)
            loaded = [
                f"`{p.name}`" for p in adapter._plugins.plugins.values() if p.status == "loaded"
            ]
            memory_count = await adapter._memory.count() if adapter._memory else 0
            lines = [
                f"⏱ 稼働時間: {uptime // 3600}時間{(uptime % 3600) // 60}分",
                f"🧠 会話モデル: `{adapter._router.primary_spec('chat')}`",
                f"💾 長期記憶: {memory_count}件",
                f"🔌 プラグイン: {', '.join(loaded) or 'なし'}",
            ]
            await interaction.response.send_message("\n".join(lines))

    def _register_plugin_command(self, name: str, description: str) -> None:
        adapter = self

        async def callback(interaction: discord.Interaction, text: str = "") -> None:
            if not await adapter._allow(interaction):
                return
            await interaction.response.defer()
            try:
                result = await adapter._plugins.execute_command(name, text)
            except Exception as e:  # noqa: BLE001
                await interaction.followup.send(f"⚠ コマンド実行エラー: {e}")
                return
            out = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            for part in split_message(out or "(結果なし)"):
                await interaction.followup.send(part)

        self._tree.add_command(
            app_commands.Command(
                name=name,
                description=(description or name)[:100],
                callback=callback,
            )
        )

    async def _allow(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is not None and interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "ごめんね、オーナー以外の指示は受けられないの。", ephemeral=True
        )
        return False
