"""
cogs/logging_cog.py — Server event logging. Listeners only.
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
    def __init__(self, bot):
        self.bot = bot

    async def _get_log_channel(self, guild):
        key    = f"log_ch_{guild.id}"
        cached = guild_config_cache.get(key)
        if cached is not None: return guild.get_channel(cached)
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch_id = config["log_channel_id"]
            guild_config_cache.set(key, ch_id, ttl=120)
            return guild.get_channel(ch_id)
        return None

    async def _send_log(self, guild, embed):
        try:
            ch = await self._get_log_channel(guild)
            if ch and isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
        except Exception as exc:
            log.warning("_send_log: %s", exc)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.guild.id != GUILD_ID or message.author.bot: return
        await self._send_log(message.guild, embeds.message_delete_log(message))

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.guild.id != GUILD_ID or before.author.bot: return
        if before.content == after.content: return
        await self._send_log(before.guild, embeds.message_edit_log(before, after))

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != GUILD_ID: return
        await db.ensure_user(member.id, member.guild.id)
        await self._send_log(member.guild, embeds.member_join_log(member))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id != GUILD_ID: return
        await self._send_log(member.guild, embeds.member_leave_log(member))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.guild.id != GUILD_ID: return
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            await self._send_log(before.guild, embeds.role_update_log(after, added, removed))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.guild.id != GUILD_ID: return
        await self._send_log(before.guild, embeds.channel_update_log(before, after))

async def setup(bot):
    await bot.add_cog(LoggingCog(bot))
