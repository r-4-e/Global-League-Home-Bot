"""
utils/embeds.py — Centralised embed factory for Elura.

Every embed displayed by the bot is built here so style stays consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord

from config import (
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_INFO,
    COLOR_MOD,
    COLOR_LOG,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def success(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(title=f"✅ {title}", description=description, color=COLOR_SUCCESS)
    e.timestamp = _now()
    return e


def error(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(title=f"❌ {title}", description=description, color=COLOR_ERROR)
    e.timestamp = _now()
    return e


def warning(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(title=f"⚠️ {title}", description=description, color=COLOR_WARNING)
    e.timestamp = _now()
    return e


def info(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(title=f"ℹ️ {title}", description=description, color=COLOR_INFO)
    e.timestamp = _now()
    return e


# ---------------------------------------------------------------------------
# Moderation action embed (standardised log format)
# ---------------------------------------------------------------------------

def moderation_action(
    *,
    action: str,
    user: discord.User | discord.Member,
    moderator: discord.User | discord.Member,
    reason: Optional[str],
    case_id: Optional[int] = None,
    extra_fields: Optional[list[tuple[str, str, bool]]] = None,
) -> discord.Embed:
    """
    Builds the canonical 🔨 Moderation Action embed used in log channels
    and DM notifications.
    """
    e = discord.Embed(title="🔨 Moderation Action", color=COLOR_MOD)
    e.add_field(
        name="User",
        value=f"{user.mention} (`{user.id}`)",
        inline=True,
    )
    e.add_field(
        name="Moderator",
        value=f"{moderator.mention} (`{moderator.id}`)",
        inline=True,
    )
    e.add_field(name="Action", value=action, inline=True)
    e.add_field(
        name="Reason",
        value=reason or "No reason provided.",
        inline=False,
    )
    if case_id is not None:
        e.add_field(name="Case ID", value=f"#{case_id}", inline=True)
    if extra_fields:
        for name, value, inline in extra_fields:
            e.add_field(name=name, value=value, inline=inline)
    e.set_thumbnail(url=user.display_avatar.url)
    e.timestamp = _now()
    return e


# ---------------------------------------------------------------------------
# DM embed sent to the punished user
# ---------------------------------------------------------------------------

def user_dm(
    *,
    guild_name: str,
    action: str,
    reason: Optional[str],
    case_id: Optional[int] = None,
    extra: str = "",
) -> discord.Embed:
    description = (
        f"You have received a **{action}** in **{guild_name}**.\n\n"
        f"**Reason:** {reason or 'No reason provided.'}"
    )
    if extra:
        description += f"\n{extra}"
    e = discord.Embed(
        title="📋 Moderation Notice",
        description=description,
        color=COLOR_WARNING,
    )
    if case_id:
        e.set_footer(text=f"Case #{case_id}")
    e.timestamp = _now()
    return e


# ---------------------------------------------------------------------------
# History / case list embed
# ---------------------------------------------------------------------------

def case_list(
    user: discord.User | discord.Member,
    cases: list[dict],
    page: int,
    total_pages: int,
) -> discord.Embed:
    e = discord.Embed(
        title=f"📋 Moderation History — {user}",
        color=COLOR_INFO,
    )
    e.set_thumbnail(url=user.display_avatar.url)
    for case in cases:
        ts = case.get("timestamp", "")[:10]
        e.add_field(
            name=f"Case #{case['case_id']} — {case['action'].upper()} ({ts})",
            value=(
                f"**Reason:** {case.get('reason') or 'No reason provided.'}\n"
                f"**Moderator:** <@{case['moderator_id']}>"
            ),
            inline=False,
        )
    e.set_footer(text=f"Page {page}/{total_pages}  •  User ID: {user.id}")
    e.timestamp = _now()
    return e


# ---------------------------------------------------------------------------
# Automod embed
# ---------------------------------------------------------------------------

def automod_action(
    *,
    user: discord.Member,
    rule: str,
    action_taken: str,
    message_preview: str = "",
) -> discord.Embed:
    e = discord.Embed(title="🤖 AutoMod Triggered", color=COLOR_WARNING)
    e.add_field(name="User",        value=f"{user.mention} (`{user.id}`)", inline=True)
    e.add_field(name="Rule",        value=rule,                            inline=True)
    e.add_field(name="Action",      value=action_taken,                    inline=True)
    if message_preview:
        e.add_field(
            name="Message",
            value=f"```{message_preview[:200]}```",
            inline=False,
        )
    e.set_thumbnail(url=user.display_avatar.url)
    e.timestamp = _now()
    return e


# ---------------------------------------------------------------------------
# Log embeds
# ---------------------------------------------------------------------------

def message_delete_log(message: discord.Message) -> discord.Embed:
    e = discord.Embed(
        title="🗑️ Message Deleted",
        color=COLOR_LOG,
        description=message.content[:1024] if message.content else "*[No text content]*",
    )
    e.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
    e.add_field(name="Channel", value=message.channel.mention, inline=True)
    e.set_footer(text=f"Message ID: {message.id}")
    e.timestamp = _now()
    return e


def message_edit_log(before: discord.Message, after: discord.Message) -> discord.Embed:
    e = discord.Embed(title="✏️ Message Edited", color=COLOR_LOG)
    e.add_field(name="Author",  value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
    e.add_field(name="Channel", value=before.channel.mention, inline=True)
    e.add_field(name="Before",  value=(before.content or "*empty*")[:1024], inline=False)
    e.add_field(name="After",   value=(after.content  or "*empty*")[:1024], inline=False)
    e.set_footer(text=f"Message ID: {before.id}")
    e.timestamp = _now()
    return e


def member_join_log(member: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="📥 Member Joined",
        color=COLOR_SUCCESS,
        description=f"{member.mention} (`{member.id}`)",
    )
    created = member.created_at.strftime("%Y-%m-%d")
    e.add_field(name="Account Created", value=created, inline=True)
    e.set_thumbnail(url=member.display_avatar.url)
    e.timestamp = _now()
    return e


def member_leave_log(member: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="📤 Member Left",
        color=COLOR_ERROR,
        description=f"**{member}** (`{member.id}`)",
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.timestamp = _now()
    return e


def role_update_log(
    member: discord.Member,
    added: list[discord.Role],
    removed: list[discord.Role],
) -> discord.Embed:
    e = discord.Embed(title="🎭 Role Update", color=COLOR_INFO)
    e.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
    if added:
        e.add_field(name="Roles Added",   value=", ".join(r.mention for r in added),   inline=False)
    if removed:
        e.add_field(name="Roles Removed", value=", ".join(r.mention for r in removed), inline=False)
    e.timestamp = _now()
    return e


def channel_update_log(
    before: discord.abc.GuildChannel,
    after: discord.abc.GuildChannel,
) -> discord.Embed:
    e = discord.Embed(title="📁 Channel Updated", color=COLOR_INFO)
    e.add_field(name="Channel", value=after.mention, inline=True)
    if before.name != after.name:
        e.add_field(name="Name",   value=f"`{before.name}` → `{after.name}`", inline=False)
    e.timestamp = _now()
    return e
