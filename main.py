"""
main.py — Elura Discord Bot Entry Point

Architecture:
  • Single guild (GUILD_ID) — all slash commands are guild-scoped for instant sync
  • setup_hook() boots the DB, loads cogs, syncs commands, starts background tasks
  • No bot.loop usage — asyncio.create_task() only
  • Global error handler for all app command errors
  • Startup validator checks required permissions and configuration
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import db
from tasks.background import expired_punishment_checker, log_maintenance_task
from utils import embeds

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("elura")

# Quiet down noisy discord.py loggers in production
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Bot class
# ---------------------------------------------------------------------------

COGS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.logging_cog",
    "cogs.setup_cog",
    "cogs.help_cog",
    "cogs.search",
    "cogs.welcome",
    "cogs.tickets",
]

# Required bot permissions (value integer)
REQUIRED_INTENTS = discord.Intents(
    guilds=True,
    members=True,
    messages=True,
    message_content=True,
    moderation=True,
)


class Elura(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=[],           # Slash-only; no prefix commands
            intents=REQUIRED_INTENTS,
            help_command=None,           # Custom /help used instead
            case_insensitive=True,
        )
        self._guild_obj = discord.Object(id=config.GUILD_ID)

    # ── setup_hook ─────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """
        Called once after login, before on_ready.
        Order: DB → cogs → command sync → background tasks.
        """
        log.info("▶ setup_hook starting…")

        # 1. Connect to Supabase
        log.info("Connecting to Supabase…")
        await db.connect()

        # 2. Ensure guild config row exists (upsert defaults)
        await db.upsert_guild_config({"guild_id": config.GUILD_ID})

        # 3. Load all cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("  ✓ Loaded cog: %s", cog)
            except Exception as exc:
                log.error("  ✗ Failed to load cog %s: %s", cog, exc)

        # 4. Sync slash commands to the single guild (instant, no global delay)
        log.info("Syncing slash commands to guild %s…", config.GUILD_ID)
        self.tree.copy_global_to(guild=self._guild_obj)
        synced = await self.tree.sync(guild=self._guild_obj)
        log.info("  Synced %d commands.", len(synced))

        # 5. Start background tasks — asyncio.create_task() ONLY
        asyncio.create_task(
            expired_punishment_checker(self),
            name="expired_punishment_checker",
        )
        asyncio.create_task(
            log_maintenance_task(self),
            name="log_maintenance_task",
        )
        log.info("  ✓ Background tasks scheduled.")

        log.info("▶ setup_hook complete.")

    # ── on_ready ───────────────────────────────────────────────────────────

    async def on_ready(self) -> None:
        log.info("━" * 60)
        log.info("  Elura is online!")
        log.info("  Logged in as : %s (%s)", self.user, self.user.id)
        log.info("  Guild        : %s", config.GUILD_ID)
        log.info("  discord.py   : %s", discord.__version__)
        log.info("━" * 60)

        await self._run_startup_validation()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="the server | /help",
            )
        )

    # ── Startup validation ─────────────────────────────────────────────────

    async def _run_startup_validation(self) -> None:
        """
        Checks required permissions, log channel, and muted role.
        Logs warnings for any missing configuration.
        """
        log.info("Running startup validation…")
        guild = self.get_guild(config.GUILD_ID)
        if guild is None:
            log.error("  ✗ Guild %s not found! Is the bot in that server?", config.GUILD_ID)
            return

        # Check bot permissions
        bot_member = guild.me
        required_perms = [
            ("ban_members",      "Ban Members"),
            ("kick_members",     "Kick Members"),
            ("moderate_members", "Moderate Members"),
            ("manage_roles",     "Manage Roles"),
            ("manage_messages",  "Manage Messages"),
            ("manage_channels",  "Manage Channels"),
            ("manage_nicknames", "Manage Nicknames"),
            ("view_audit_log",   "View Audit Log"),
        ]
        for perm, label in required_perms:
            if not getattr(bot_member.guild_permissions, perm, False):
                log.warning("  ⚠ Missing permission: %s", label)

        # Check guild config
        cfg = await db.get_guild_config(guild.id)
        if not cfg or not cfg.get("setup_complete"):
            log.warning("  ⚠ Setup not complete — run /setup in the guild.")
            return

        log_ch_id = cfg.get("log_channel_id")
        if log_ch_id:
            ch = guild.get_channel(log_ch_id)
            if ch is None:
                log.warning("  ⚠ Log channel (ID: %s) not found.", log_ch_id)
            else:
                log.info("  ✓ Log channel: #%s", ch.name)
        else:
            log.warning("  ⚠ Log channel not configured.")

        muted_role_id = cfg.get("muted_role_id")
        if muted_role_id:
            role = guild.get_role(muted_role_id)
            if role is None:
                log.warning("  ⚠ Muted role (ID: %s) not found.", muted_role_id)
            else:
                log.info("  ✓ Muted role: @%s", role.name)
        else:
            log.warning("  ⚠ Muted role not configured.")

        log.info("Startup validation complete.")

    # ── Global app_command error handler ──────────────────────────────────

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Catch-all for any unhandled slash command errors."""

        # Unwrap TransformerError to get the real cause
        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original  # type: ignore[assignment]

        msg: Optional[str] = None

        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You don't have permission to use this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "❌ I don't have the required permissions to do that."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"❌ This command is on cooldown. Try again in `{error.retry_after:.1f}s`."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "❌ This command can only be used in a server."
        elif isinstance(error, app_commands.TransformerError):
            msg = f"❌ Invalid input: `{error.value}` could not be resolved."
        elif isinstance(error, discord.Forbidden):
            msg = "❌ I don't have permission to perform that action."
        elif isinstance(error, discord.NotFound):
            msg = "❌ The requested resource was not found."
        else:
            log.error("Unhandled app command error: %s", error, exc_info=error)
            msg = "❌ Something went wrong. Please try again later."

        if msg:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        embed=embeds.error("Error", msg), ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        embed=embeds.error("Error", msg), ephemeral=True
                    )
            except Exception as send_err:
                log.warning("Could not send error response: %s", send_err)

    # ── Generic event error (non-command) ──────────────────────────────────

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        log.exception("Unhandled exception in event: %s", event_method)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def keep_alive() -> None:
    """Minimal HTTP server so Render sees an open port and keeps the service alive."""
    from aiohttp import web

    async def handle(request: web.Request) -> web.Response:
        return web.Response(text="Elura is running.")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()
    log.info("Keep-alive server listening on port %s", os.environ.get("PORT", 8080))


async def main() -> None:
    if not config.TOKEN:
        log.critical("TOKEN is not set. Cannot start.")
        sys.exit(1)
    if not config.GUILD_ID:
        log.critical("GUILD_ID is not set. Cannot start.")
        sys.exit(1)
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        log.critical("SUPABASE_URL / SUPABASE_KEY not set. Cannot start.")
        sys.exit(1)

    await keep_alive()

    bot = Elura()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
