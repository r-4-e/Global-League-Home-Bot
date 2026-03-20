"""
cogs/logging_cog.py — Event-based server logging for Elura.

All events are sent to the configured log channel as structured embeds.
Gracefully skips if no log channel is configured.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils import embeds
from utils.cache import guild_config_cache

log = logging.getLogger(__name__)


class LoggingCog(commands.Cog, name="Logging"):
    """Listens to guild events and forwards them to the log channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Internal helper ────────────────────────────────────────────────────

    async def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Return the configured log channel, or None if not set."""
        key = f"log_ch_{guild.id}"
        cached = guild_config_cache.get(key)
        if cached is not None:
            return guild.get_channel(cached)  # type: ignore[return-value]

        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch_id = config["log_channel_id"]
            guild_config_cache.set(key, ch_id, ttl=120)
            return guild.get_channel(ch_id)  # type: ignore[return-value]
        return None

    async def _send_log(
        self, guild: discord.Guild, embed: discord.Embed
    ) -> None:
        try:
            ch = await self._get_log_channel(guild)
            if ch and isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
        except Exception as exc:
            log.warning("_send_log failed: %s", exc)

    # ── Message events ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.guild.id != GUILD_ID:
            return
        if message.author.bot:
            return
        await self._send_log(message.guild, embeds.message_delete_log(message))

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if not before.guild or before.guild.id != GUILD_ID:
            return
        if before.author.bot:
            return
        if before.content == after.content:
            return  # Only embed / attachment changes — skip
        await self._send_log(before.guild, embeds.message_edit_log(before, after))

    # ── Member events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != GUILD_ID:
            return
        await db.ensure_user(member.id, member.guild.id)
        await self._send_log(member.guild, embeds.member_join_log(member))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != GUILD_ID:
            return
        await self._send_log(member.guild, embeds.member_leave_log(member))

    # ── Role update ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        if before.guild.id != GUILD_ID:
            return
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            await self._send_log(
                before.guild, embeds.role_update_log(after, added, removed)
            )

    # ── Channel update ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        if before.guild.id != GUILD_ID:
            return
        await self._send_log(before.guild, embeds.channel_update_log(before, after))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
