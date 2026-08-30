"""
cogs/stats.py — Live Server Stats Channels

Creates a category with 3 voice channels showing live stats.
Updates every 10 minutes (Discord rate limits channel edits).

Channels created:
    📊 GL Stats (category)
    ├── 👥 Members: 1,234
    ├── 🧑 Humans: 1,200
    └── 🤖 Bots: 34

Commands:
    gl.stats_setup   — create the category and channels (Admin only)
    gl.stats_remove  — delete the category and channels (Admin only)
    gl.stats_update  — force an immediate update (Admin only)
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

import config
from database import db

log = logging.getLogger("elura.stats")

CATEGORY_NAME = "📊 GL Stats"
UPDATE_INTERVAL_MINUTES = 10


def _channel_names(guild: discord.Guild) -> dict[str, str]:
    total  = guild.member_count or 0
    bots   = sum(1 for m in guild.members if m.bot)
    humans = total - bots
    return {
        "members": f"👥 Members: {total:,}",
        "humans":  f"🧑 Humans: {humans:,}",
        "bots":    f"🤖 Bots: {bots:,}",
    }


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self._update_loop.start()

    def cog_unload(self) -> None:
        self._update_loop.cancel()

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_channel_ids(self) -> dict | None:
        try:
            cfg = await db.get_guild_config(config.GUILD_ID)
            return (cfg or {}).get("stats_channels")
        except Exception:
            return None

    async def _save_channel_ids(self, data: dict) -> None:
        try:
            await db.upsert_guild_config({
                "guild_id": config.GUILD_ID,
                "stats_channels": data,
            })
        except Exception as exc:
            log.warning("Could not save stats channel IDs: %s", exc)

    async def _do_update(self, guild: discord.Guild) -> bool:
        ids = await self._get_channel_ids()
        if not ids:
            return False

        names = _channel_names(guild)
        updated = 0

        for key, new_name in names.items():
            ch_id = ids.get(key)
            if not ch_id:
                continue
            ch = guild.get_channel(int(ch_id))
            if ch is None:
                continue
            if ch.name != new_name:
                try:
                    await ch.edit(name=new_name, reason="Stats update")
                    updated += 1
                except discord.Forbidden:
                    log.warning("Missing permission to edit stats channel %s", ch_id)
                except discord.HTTPException as exc:
                    log.warning("Failed to edit stats channel: %s", exc)

        return updated > 0

    # ── Loop ──────────────────────────────────────────────────────────────────

    @tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
    async def _update_loop(self) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return
        await self._do_update(guild)

    @_update_loop.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.command(name="stats_setup")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def stats_setup(self, ctx: commands.Context) -> None:
        """Create the stats category and voice channels. Admin only."""
        guild = ctx.guild

        # Check if already set up
        existing = await self._get_channel_ids()
        if existing:
            await ctx.send(
                "⚠️ Stats channels already exist. "
                "Run `gl.stats_remove` first if you want to recreate them."
            )
            return

        async with ctx.typing():
            # No one can join or speak — view only
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    connect=False,
                    view_channel=True,
                ),
                guild.me: discord.PermissionOverwrite(
                    connect=True,
                    manage_channels=True,
                    view_channel=True,
                ),
            }

            try:
                category = await guild.create_category(
                    name=CATEGORY_NAME,
                    overwrites=overwrites,
                    reason="GL Stats setup",
                )
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to create categories.")
                return

            names = _channel_names(guild)
            channel_ids = {}

            for key, name in names.items():
                try:
                    vc = await guild.create_voice_channel(
                        name=name,
                        category=category,
                        overwrites=overwrites,
                        reason="GL Stats setup",
                    )
                    channel_ids[key] = vc.id
                except discord.Forbidden:
                    await ctx.send("❌ I don't have permission to create voice channels.")
                    await category.delete()
                    return

            channel_ids["category"] = category.id
            await self._save_channel_ids(channel_ids)

        embed = discord.Embed(
            title="✅ Stats Channels Created",
            description=(
                f"Category **{CATEGORY_NAME}** created with 3 stat channels.\n"
                f"Updates every **{UPDATE_INTERVAL_MINUTES} minutes** automatically."
            ),
            color=0x2ECC71,
        )
        embed.add_field(name="👥 Members", value=names["members"], inline=True)
        embed.add_field(name="🧑 Humans",  value=names["humans"],  inline=True)
        embed.add_field(name="🤖 Bots",    value=names["bots"],    inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="stats_remove")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def stats_remove(self, ctx: commands.Context) -> None:
        """Delete the stats category and channels. Admin only."""
        ids = await self._get_channel_ids()
        if not ids:
            await ctx.send("❌ No stats channels found.")
            return

        async with ctx.typing():
            for key, ch_id in ids.items():
                ch = ctx.guild.get_channel(int(ch_id))
                if ch:
                    try:
                        await ch.delete(reason="GL Stats removed")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            await self._save_channel_ids(None)

        await ctx.send("✅ Stats channels removed.")

    @commands.command(name="stats_update")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def stats_update(self, ctx: commands.Context) -> None:
        """Force an immediate stats update. Admin only."""
        async with ctx.typing():
            ok = await self._do_update(ctx.guild)
        if ok:
            await ctx.send("✅ Stats channels updated.", delete_after=5)
        else:
            await ctx.send(
                "❌ Nothing updated — either stats channels don't exist "
                "(`gl.stats_setup`) or names are already current."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))
