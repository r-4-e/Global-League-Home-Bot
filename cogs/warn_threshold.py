"""
cogs/warn_threshold.py — Automatic punishment escalation based on warning count.

Thresholds (applied automatically after every /warn):

  🟢 Minor
    3  warns → 30 min timeout
    4  warns → 1 hr timeout
    5  warns → 2 hr timeout

  🟡 Medium
    6  warns → Kick + 3 hr timeout
    7  warns → Kick + 4 hr timeout
    8  warns → Kick
    9  warns → 1 day ban
    10 warns → 1.5 day ban
    11 warns → 2 day ban

  🔴 Major
    12 warns → 3 day ban
    13 warns → 5 day ban
    14 warns → 7 day ban
    15 warns → Permanent ban
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Threshold map — warn_count: (action, duration_minutes, label, tier)
# ---------------------------------------------------------------------------

THRESHOLDS: dict[int, tuple[str, Optional[int], str, str]] = {
    # count: (action, ban_days or timeout_minutes, label, tier)
    3:  ("timeout", 30,          "30 min timeout",    "🟢 Minor"),
    4:  ("timeout", 60,          "1 hr timeout",      "🟢 Minor"),
    5:  ("timeout", 120,         "2 hr timeout",      "🟢 Minor"),
    6:  ("kick+timeout", 180,    "Kick + 3 hr timeout","🟡 Medium"),
    7:  ("kick+timeout", 240,    "Kick + 4 hr timeout","🟡 Medium"),
    8:  ("kick", None,           "Kick",              "🟡 Medium"),
    9:  ("ban", 1,               "1 day ban",         "🟡 Medium"),
    10: ("ban", 2,               "1.5 day ban",       "🟡 Medium"),  # stored as 36h
    11: ("ban", 2,               "2 day ban",         "🟡 Medium"),
    12: ("ban", 3,               "3 day ban",         "🔴 Major"),
    13: ("ban", 5,               "5 day ban",         "🔴 Major"),
    14: ("ban", 7,               "7 day ban",         "🔴 Major"),
    15: ("ban", None,            "Permanent ban",     "🔴 Major"),
}

# Exact durations for special cases
BAN_DURATIONS: dict[int, timedelta] = {
    9:  timedelta(days=1),
    10: timedelta(hours=36),
    11: timedelta(days=2),
    12: timedelta(days=3),
    13: timedelta(days=5),
    14: timedelta(days=7),
}


async def _get_active_warn_count(user_id: int, guild_id: int) -> int:
    """Count active WARN cases for a user."""
    cases, total = await db.get_cases(user_id, guild_id, page=1, page_size=1)
    # Fetch all to count warns specifically
    all_cases, total_all = await db.get_cases(user_id, guild_id, page=1, page_size=500)
    return sum(1 for c in all_cases if c.get("action") == "WARN" and c.get("active"))


async def _send_log(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> None:
    try:
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch = guild.get_channel(config["log_channel_id"])
            if isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
    except Exception as exc:
        log.warning("warn_threshold log failed: %s", exc)


async def apply_threshold(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
    warn_count: int,
) -> Optional[str]:
    """
    Check warn count against thresholds and apply the appropriate punishment.
    Returns a description of what was applied, or None if no threshold hit.
    """
    if warn_count not in THRESHOLDS:
        return None

    action, duration, label, tier = THRESHOLDS[warn_count]
    reason = f"[Auto] Warning threshold reached ({warn_count} warns) — {label}"
    applied = None

    try:
        # ── Timeout ───────────────────────────────────────────────────────
        if action == "timeout" and duration:
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=reason)
            await db.create_case(
                user_id=member.id,
                moderator_id=bot.user.id,
                action="TIMEOUT",
                reason=reason,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=duration),
                guild_id=guild.id,
            )
            applied = f"{tier} — {label}"

        # ── Kick + Timeout ────────────────────────────────────────────────
        elif action == "kick+timeout" and duration:
            # Apply timeout record first, then kick
            await db.create_case(
                user_id=member.id,
                moderator_id=bot.user.id,
                action="KICK",
                reason=reason,
                guild_id=guild.id,
            )
            try:
                dm_embed = discord.Embed(
                    title="📋 Moderation Notice",
                    description=(
                        f"You have been **kicked** from **{guild.name}**.\n\n"
                        f"**Reason:** {reason}\n"
                        f"**Warns:** {warn_count}"
                    ),
                    color=0xF39C12,
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
            await guild.kick(member, reason=reason)
            applied = f"{tier} — {label}"

        # ── Kick ──────────────────────────────────────────────────────────
        elif action == "kick":
            await db.create_case(
                user_id=member.id,
                moderator_id=bot.user.id,
                action="KICK",
                reason=reason,
                guild_id=guild.id,
            )
            try:
                dm_embed = discord.Embed(
                    title="📋 Moderation Notice",
                    description=(
                        f"You have been **kicked** from **{guild.name}**.\n\n"
                        f"**Reason:** {reason}\n"
                        f"**Warns:** {warn_count}"
                    ),
                    color=0xF39C12,
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
            await guild.kick(member, reason=reason)
            applied = f"{tier} — {label}"

        # ── Timed Ban ─────────────────────────────────────────────────────
        elif action == "ban" and duration is not None:
            ban_duration = BAN_DURATIONS.get(warn_count)
            expires_at   = datetime.now(timezone.utc) + ban_duration if ban_duration else None
            await db.create_case(
                user_id=member.id,
                moderator_id=bot.user.id,
                action="BAN",
                reason=reason,
                expires_at=expires_at,
                guild_id=guild.id,
            )
            try:
                dm_embed = discord.Embed(
                    title="📋 Moderation Notice",
                    description=(
                        f"You have been **banned** from **{guild.name}**.\n\n"
                        f"**Reason:** {reason}\n"
                        f"**Duration:** {label}\n"
                        f"**Warns:** {warn_count}"
                    ),
                    color=0xE74C3C,
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
            await guild.ban(member, reason=reason, delete_message_days=0)
            applied = f"{tier} — {label}"

        # ── Permanent Ban ─────────────────────────────────────────────────
        elif action == "ban" and duration is None:
            await db.create_case(
                user_id=member.id,
                moderator_id=bot.user.id,
                action="BAN",
                reason=reason,
                guild_id=guild.id,
            )
            try:
                dm_embed = discord.Embed(
                    title="📋 Moderation Notice",
                    description=(
                        f"You have been **permanently banned** from **{guild.name}**.\n\n"
                        f"**Reason:** {reason}\n"
                        f"**Warns:** {warn_count}"
                    ),
                    color=0xE74C3C,
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
            await guild.ban(member, reason=reason, delete_message_days=0)
            applied = f"{tier} — {label}"

    except discord.Forbidden:
        log.warning("warn_threshold: no permission to punish %s", member.id)
        return None
    except Exception as exc:
        log.error("warn_threshold apply error: %s", exc)
        return None

    # Log to log channel
    if applied:
        e = discord.Embed(
            title="⚒️ Warning Threshold Triggered",
            color=0xFF0000 if "🔴" in tier else (0xF39C12 if "🟡" in tier else 0x2ECC71),
        )
        e.add_field(name="User",       value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Tier",       value=tier,                                inline=True)
        e.add_field(name="Action",     value=label,                               inline=True)
        e.add_field(name="Warn Count", value=str(warn_count),                     inline=True)
        e.set_thumbnail(url=member.display_avatar.url)
        e.timestamp = datetime.now(timezone.utc)
        await _send_log(bot, guild, e)

    return applied


class WarnThresholdCog(commands.Cog, name="WarnThreshold"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_warn_issued(
        self,
        guild: discord.Guild,
        member: discord.Member,
        warn_count: int,
    ) -> None:
        """Called by moderation.py after a warn is issued."""
        await apply_threshold(self.bot, guild, member, warn_count)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WarnThresholdCog(bot))
