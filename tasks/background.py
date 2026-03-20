"""
tasks/background.py — Background tasks for Elura.

All tasks are started inside Bot.setup_hook() using asyncio.create_task().
❌ No bot.loop usage anywhere.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import GUILD_ID, PUNISHMENT_CHECK_INTERVAL
from database import db

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Expired punishment checker
# ---------------------------------------------------------------------------

async def expired_punishment_checker(bot: commands.Bot) -> None:
    """
    Runs every PUNISHMENT_CHECK_INTERVAL seconds.
    Finds active cases whose expires_at has passed and reverses them:
      - MUTE  → remove muted role
      - TIMEOUT → clear via Discord API (timeout already expired; just mark case inactive)
    """
    await bot.wait_until_ready()
    log.info("[Task] expired_punishment_checker started.")

    while not bot.is_closed():
        try:
            await _process_expired(bot)
        except Exception as exc:
            log.error("[Task] expired_punishment_checker error: %s", exc)

        await asyncio.sleep(PUNISHMENT_CHECK_INTERVAL)


async def _process_expired(bot: commands.Bot) -> None:
    expired = await db.get_active_timed_punishments(GUILD_ID)
    if not expired:
        return

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        log.warning("[Task] Guild %s not found in cache.", GUILD_ID)
        return

    config = await db.get_guild_config(GUILD_ID)
    muted_role_id = config.get("muted_role_id") if config else None

    for case in expired:
        case_id  = case["case_id"]
        action   = case["action"]
        user_id  = case["user_id"]

        # Mark case inactive first to prevent double-processing
        await db.deactivate_case(case_id)

        member = guild.get_member(user_id)
        if member is None:
            # User left the guild — just log
            log.info("[Task] Case #%s: user %s not in guild, skipped.", case_id, user_id)
            continue

        try:
            if action == "MUTE" and muted_role_id:
                muted_role = guild.get_role(muted_role_id)
                if muted_role and muted_role in member.roles:
                    await member.remove_roles(
                        muted_role, reason=f"[Auto] Mute expired — Case #{case_id}"
                    )
                    log.info("[Task] Unmuted %s (case #%s).", member, case_id)

            elif action == "TIMEOUT":
                # Discord handles timeout expiry automatically, but we can explicitly
                # clear it in case we're slightly early.
                if member.timed_out:
                    await member.timeout(None, reason=f"[Auto] Timeout expired — Case #{case_id}")
                    log.info("[Task] Removed timeout from %s (case #%s).", member, case_id)

        except discord.Forbidden:
            log.warning("[Task] No permission to un-punish %s (case #%s).", member, case_id)
        except Exception as exc:
            log.error("[Task] Error processing case #%s: %s", case_id, exc)


# ---------------------------------------------------------------------------
# Log maintenance (placeholder — extend as needed)
# ---------------------------------------------------------------------------

async def log_maintenance_task(bot: commands.Bot) -> None:
    """
    Periodic housekeeping task.
    Currently: just verifies log channel is still accessible every 10 minutes.
    Extend as needed (e.g. cleanup old cases, prune old help stats, etc.)
    """
    await bot.wait_until_ready()
    log.info("[Task] log_maintenance_task started.")

    while not bot.is_closed():
        await asyncio.sleep(600)  # run every 10 minutes
        try:
            config = await db.get_guild_config(GUILD_ID)
            if not config:
                continue
            guild = bot.get_guild(GUILD_ID)
            if guild is None:
                continue

            lc_id = config.get("log_channel_id")
            if lc_id and not guild.get_channel(lc_id):
                log.warning(
                    "[Maintenance] Configured log channel %s not found in guild %s.",
                    lc_id, GUILD_ID,
                )
        except Exception as exc:
            log.error("[Task] log_maintenance_task error: %s", exc)
