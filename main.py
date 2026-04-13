"""
main.py — Global League Bot Entry Point
Prefix: gl.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

import config
from database import db
from tasks.background import expired_punishment_checker, log_maintenance_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("elura")
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

COGS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.logging_cog",
    "cogs.setup_cog",
    "cogs.help_cog",
    "cogs.search",
    "cogs.welcome",
    "cogs.tickets",
    "cogs.info",
    "cogs.economy",
    "cogs.utility",
    "cogs.about",
    "cogs.warn_threshold",
    "cogs.election",
    "cogs.fun",
]

REQUIRED_INTENTS = discord.Intents(
    guilds=True,
    members=True,
    messages=True,
    message_content=True,
    moderation=True,
)


class GlobalLeagueBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="gl.",
            intents=REQUIRED_INTENTS,
            help_command=None,
            case_insensitive=True,
        )

    async def setup_hook(self) -> None:
        log.info("▶ setup_hook starting…")

        log.info("Connecting to Supabase…")
        await db.connect()
        await db.upsert_guild_config({"guild_id": config.GUILD_ID})

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("  ✓ Loaded cog: %s", cog)
            except Exception as exc:
                log.error("  ✗ Failed to load cog %s: %s", cog, exc)

        asyncio.create_task(expired_punishment_checker(self), name="expired_punishment_checker")
        asyncio.create_task(log_maintenance_task(self), name="log_maintenance_task")
        log.info("▶ setup_hook complete.")

    async def on_ready(self) -> None:
        log.info("━" * 50)
        log.info("  Global League Bot is online!")
        log.info("  Logged in as : %s (%s)", self.user, self.user.id)
        log.info("  Prefix       : gl.")
        log.info("  Guild        : %s", config.GUILD_ID)
        log.info("━" * 50)
        await self._run_startup_validation()
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="Global League | gl.help")
        )

    async def _run_startup_validation(self) -> None:
        guild = self.get_guild(config.GUILD_ID)
        if guild is None:
            log.error("  ✗ Guild %s not found!", config.GUILD_ID)
            return
        bot_member = guild.me
        required_perms = [
            ("ban_members",      "Ban Members"),
            ("kick_members",     "Kick Members"),
            ("moderate_members", "Moderate Members"),
            ("manage_roles",     "Manage Roles"),
            ("manage_messages",  "Manage Messages"),
            ("manage_channels",  "Manage Channels"),
            ("manage_nicknames", "Manage Nicknames"),
        ]
        for perm, label in required_perms:
            if not getattr(bot_member.guild_permissions, perm, False):
                log.warning("  ⚠ Missing permission: %s", label)

        cfg = await db.get_guild_config(guild.id)
        if not cfg or not cfg.get("setup_complete"):
            log.warning("  ⚠ Setup not complete — run gl.setup")
            return

        log_ch_id = cfg.get("log_channel_id")
        if log_ch_id:
            ch = guild.get_channel(log_ch_id)
            if ch is None:
                log.warning("  ⚠ Log channel not found.")
            else:
                log.info("  ✓ Log channel: #%s", ch.name)
        else:
            log.warning("  ⚠ Log channel not configured.")

        muted_role_id = cfg.get("muted_role_id")
        if muted_role_id:
            role = guild.get_role(muted_role_id)
            if role is None:
                log.warning("  ⚠ Muted role not found.")
            else:
                log.info("  ✓ Muted role: @%s", role.name)
        else:
            log.warning("  ⚠ Muted role not configured.")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`. Use `gl.help {ctx.command.name}` for usage.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Invalid argument. Use `gl.help {ctx.command.name}` for usage.")
        elif isinstance(error, commands.CheckFailure):
            return  # Permission checks send their own messages
        else:
            log.error("Unhandled command error in %s: %s", ctx.command, error, exc_info=error)
            await ctx.send("❌ Something went wrong. Try again later.")

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        log.exception("Unhandled exception in event: %s", event_method)


# ---------------------------------------------------------------------------
# Keep-alive server for Render
# ---------------------------------------------------------------------------

async def keep_alive() -> None:
    from aiohttp import web

    async def handle(request: web.Request) -> web.Response:
        return web.Response(text="Global League Bot is running.")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()
    log.info("Keep-alive server listening on port %s", os.environ.get("PORT", 8080))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    if not config.TOKEN:
        log.critical("TOKEN is not set.")
        sys.exit(1)
    if not config.GUILD_ID:
        log.critical("GUILD_ID is not set.")
        sys.exit(1)
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        log.critical("SUPABASE credentials not set.")
        sys.exit(1)

    await keep_alive()
    bot = GlobalLeagueBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
