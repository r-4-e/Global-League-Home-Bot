"""
cogs/warn_threshold.py — Auto punishment on warn thresholds. Prefix: gl.

Security fixes:
  1. Auto-punishments are capped at the issuing moderator's own permission level.
     A Trial Moderator (Tier 3) spamming warns cannot trigger a ban — the threshold
     escalation is capped at timeout (the highest action they can do manually).
  2. Bots cannot be warned or moderated by staff.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import can_auto_punish, _member_tier, get_tier_name

log = logging.getLogger(__name__)

THRESHOLDS = {
    3:  ("timeout",      30,   "30 min timeout",      "🟢 Minor"),
    4:  ("timeout",      60,   "1 hr timeout",        "🟢 Minor"),
    5:  ("timeout",      120,  "2 hr timeout",        "🟢 Minor"),
    6:  ("kick+timeout", 180,  "Kick + 3 hr timeout", "🟡 Medium"),
    7:  ("kick+timeout", 240,  "Kick + 4 hr timeout", "🟡 Medium"),
    8:  ("kick",         None, "Kick",                "🟡 Medium"),
    9:  ("ban",          1,    "1 day ban",           "🟡 Medium"),
    10: ("ban",          2,    "1.5 day ban",         "🟡 Medium"),
    11: ("ban",          2,    "2 day ban",           "🟡 Medium"),
    12: ("ban",          3,    "3 day ban",           "🔴 Major"),
    13: ("ban",          5,    "5 day ban",           "🔴 Major"),
    14: ("ban",          7,    "7 day ban",           "🔴 Major"),
    15: ("ban",          None, "Permanent ban",       "🔴 Major"),
}

BAN_DURATIONS = {
    9:  timedelta(days=1),
    10: timedelta(hours=36),
    11: timedelta(days=2),
    12: timedelta(days=3),
    13: timedelta(days=5),
    14: timedelta(days=7),
}

# Map action strings to permission category for cap check
ACTION_PERM_MAP = {
    "timeout":      "timeout",
    "kick+timeout": "kick",
    "kick":         "kick",
    "ban":          "ban",
}


async def _send_log(bot, guild, embed):
    try:
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch = guild.get_channel(config["log_channel_id"])
            if isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
    except Exception as exc:
        log.warning("warn_threshold log: %s", exc)


async def _send_log_capped(bot, guild, moderator, member, warn_count, action, capped_to):
    """Log to staff when a threshold is hit but capped due to moderator tier."""
    try:
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch = guild.get_channel(config["log_channel_id"])
            if isinstance(ch, discord.TextChannel):
                e = discord.Embed(
                    title="⚠️ Threshold Capped — Permission Limit",
                    description=(
                        f"{member.mention} hit warn threshold **{warn_count}** "
                        f"(would trigger **{action}**) but the issuing moderator "
                        f"**{moderator}** ({get_tier_name(_member_tier(moderator))}) "
                        f"can only auto-escalate up to **{capped_to}**.\n\n"
                        f"A higher-ranked staff member should review this case."
                    ),
                    color=0xF39C12,
                )
                e.add_field(name="User",       value=f"{member.mention} (`{member.id}`)", inline=True)
                e.add_field(name="Moderator",  value=f"{moderator.mention}",              inline=True)
                e.add_field(name="Warn Count", value=str(warn_count),                     inline=True)
                e.add_field(name="Intended",   value=action,                              inline=True)
                e.add_field(name="Capped at",  value=capped_to,                           inline=True)
                e.timestamp = datetime.now(timezone.utc)
                await ch.send(embed=e)
    except Exception as exc:
        log.warning("warn_threshold cap log: %s", exc)


async def apply_threshold(bot, guild, member, warn_count, moderator: discord.Member = None):
    """
    Apply the auto-punishment for a given warn count.

    moderator: the staff member who issued the warn. When provided,
               the punishment is capped at their permission level.
               When None (legacy call), no cap is applied.
    """
    if warn_count not in THRESHOLDS:
        return None

    action, duration, label, tier = THRESHOLDS[warn_count]
    reason  = f"[Auto] {warn_count} warnings — {label}"

    # ── Security check 1: block actions on bots ───────────────────────────────
    if member.bot:
        log.warning(
            "warn_threshold: attempted to apply threshold to bot %s (%s) — blocked.",
            member, member.id,
        )
        return None

    # ── Security check 2: cap punishment at moderator's own permission level ──
    if moderator is not None and not moderator.bot:
        perm_action = ACTION_PERM_MAP.get(action, action)
        allowed, cap_reason = can_auto_punish(moderator, perm_action)
        if not allowed:
            log.warning(
                "warn_threshold: %s (%s) tried to trigger %s on %s — capped.",
                moderator, get_tier_name(_member_tier(moderator)), action, member.id,
            )
            await _send_log_capped(bot, guild, moderator, member, warn_count, action, cap_reason.split("up to **")[1].split("**")[0] if "up to **" in cap_reason else "lower action")
            return f"⚠️ Threshold capped — {cap_reason}"

    applied = None

    try:
        if action == "timeout" and duration:
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=reason)
            await db.create_case(
                user_id=member.id, moderator_id=bot.user.id, action="TIMEOUT",
                reason=reason,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=duration),
                guild_id=guild.id,
            )
            applied = f"{tier} — {label}"

        elif action in ("kick+timeout", "kick"):
            await db.create_case(
                user_id=member.id, moderator_id=bot.user.id,
                action="KICK", reason=reason, guild_id=guild.id,
            )
            try:
                await member.send(embed=discord.Embed(
                    title="📋 Moderation Notice",
                    description=f"You were **kicked** from **{guild.name}**.\n\n**Reason:** {reason}",
                    color=0xF39C12,
                ))
            except discord.Forbidden:
                pass
            await guild.kick(member, reason=reason)
            applied = f"{tier} — {label}"

        elif action == "ban":
            ban_dur    = BAN_DURATIONS.get(warn_count)
            expires_at = datetime.now(timezone.utc) + ban_dur if ban_dur else None
            ban_label  = label if duration is None else f"{label}"
            await db.create_case(
                user_id=member.id, moderator_id=bot.user.id, action="BAN",
                reason=reason, expires_at=expires_at, guild_id=guild.id,
            )
            try:
                await member.send(embed=discord.Embed(
                    title="📋 Moderation Notice",
                    description=(
                        f"You were **{'permanently ' if duration is None else ''}banned** "
                        f"from **{guild.name}**.\n\n**Reason:** {reason}\n**Duration:** {ban_label}"
                    ),
                    color=0xE74C3C,
                ))
            except discord.Forbidden:
                pass
            await guild.ban(member, reason=reason, delete_message_days=0)
            applied = f"{tier} — {label}"

    except discord.Forbidden:
        log.warning("warn_threshold: no permission for %s", member.id)
        return None
    except Exception as exc:
        log.error("warn_threshold error: %s", exc)
        return None

    if applied:
        color = 0xFF0000 if "🔴" in tier else (0xF39C12 if "🟡" in tier else 0x2ECC71)
        e = discord.Embed(title="⚒️ Warning Threshold Triggered", color=color)
        e.add_field(name="User",       value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Tier",       value=tier,                                inline=True)
        e.add_field(name="Action",     value=label,                               inline=True)
        e.add_field(name="Warn Count", value=str(warn_count),                     inline=True)
        if moderator:
            e.add_field(name="Issued by", value=moderator.mention, inline=True)
        e.set_thumbnail(url=member.display_avatar.url)
        e.timestamp = datetime.now(timezone.utc)
        await _send_log(bot, guild, e)

    return applied


class WarnThresholdCog(commands.Cog, name="WarnThreshold"):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(WarnThresholdCog(bot))
