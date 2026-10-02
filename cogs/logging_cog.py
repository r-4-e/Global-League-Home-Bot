"""
cogs/logging_cog.py — Full server event logging. Prefix: gl.

Covered events:
  Messages    : delete, bulk delete, edit
  Members     : join, leave, ban, unban, kick, role update,
                nickname change, timeout apply/remove,
                username change, avatar change
  Channels    : create, delete, update
  Roles       : create, delete, update
  Voice       : join, leave, move, server-mute/deafen, self-mute/deafen, stream start/stop
  Invites     : create, delete
  Threads     : create, delete, archive, unarchive
  Guild       : bot added, emoji update, sticker update
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.cache import guild_config_cache

log = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "Unknown"
    return discord.utils.format_dt(dt, "F")


def _avatar_url(user: discord.User | discord.Member) -> str:
    return user.display_avatar.url


def _truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


async def _fetch_audit(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int | None = None,
    limit: int = 5,
) -> discord.AuditLogEntry | None:
    """Return the most recent audit log entry matching action (and optionally target)."""
    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            if target_id is None or entry.target.id == target_id:
                # only entries within the last 10 seconds are fresh
                age = (_now() - entry.created_at).total_seconds()
                if age <= 10:
                    return entry
    except (discord.Forbidden, discord.HTTPException):
        pass
    return None


# ── Embed builders ────────────────────────────────────────────────────────────

def _base(title: str, color: int) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=_now())
    return e


# ─── Messages ─────────────────────────────────────────────────────────────────

def _embed_message_delete(message: discord.Message) -> discord.Embed:
    e = _base("🗑️ Message Deleted", 0xE74C3C)
    e.add_field(name="Author",  value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
    e.add_field(name="Channel", value=message.channel.mention, inline=True)
    if message.content:
        e.add_field(name="Content", value=_truncate(message.content), inline=False)
    if message.attachments:
        e.add_field(
            name="Attachments",
            value="\n".join(a.filename for a in message.attachments),
            inline=False,
        )
    e.set_footer(text=f"Message ID: {message.id}")
    e.set_thumbnail(url=_avatar_url(message.author))
    return e


def _embed_bulk_delete(channel: discord.TextChannel, count: int) -> discord.Embed:
    e = _base("🗑️ Bulk Message Delete", 0xC0392B)
    e.add_field(name="Channel",         value=channel.mention, inline=True)
    e.add_field(name="Messages Deleted", value=str(count),      inline=True)
    return e


def _embed_message_edit(before: discord.Message, after: discord.Message) -> discord.Embed:
    e = _base("✏️ Message Edited", 0x3498DB)
    e.add_field(name="Author",  value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
    e.add_field(name="Channel", value=before.channel.mention, inline=True)
    e.add_field(name="Jump",    value=f"[Click here]({after.jump_url})", inline=True)
    e.add_field(name="Before",  value=_truncate(before.content or "*empty*", 512), inline=False)
    e.add_field(name="After",   value=_truncate(after.content  or "*empty*", 512), inline=False)
    e.set_footer(text=f"Message ID: {before.id}")
    e.set_thumbnail(url=_avatar_url(before.author))
    return e


# ─── Members ─────────────────────────────────────────────────────────────────

def _embed_member_join(member: discord.Member) -> discord.Embed:
    age = _now() - member.created_at
    age_str = f"{age.days} days old"
    new_flag = " ⚠️ New account!" if age.days < 7 else ""
    e = _base("📥 Member Joined", 0x2ECC71)
    e.description = f"{member.mention} joined the server."
    e.add_field(name="Account Created", value=f"{_ts(member.created_at)}\n{age_str}{new_flag}", inline=True)
    e.add_field(name="Member Count",    value=str(member.guild.member_count), inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_member_leave(member: discord.Member) -> discord.Embed:
    joined = _ts(member.joined_at) if member.joined_at else "Unknown"
    roles  = [r.mention for r in member.roles if r.name != "@everyone"]
    e = _base("📤 Member Left", 0x95A5A6)
    e.description = f"**{member}** (`{member.id}`) left the server."
    e.add_field(name="Joined",       value=joined,                               inline=True)
    e.add_field(name="Member Count", value=str(member.guild.member_count),       inline=True)
    if roles:
        e.add_field(name="Roles", value=" ".join(roles[-10:]) or "None", inline=False)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_ban(
    member: discord.User | discord.Member,
    moderator: discord.Member | None,
    reason: str | None,
) -> discord.Embed:
    e = _base("🔨 Member Banned", 0xC0392B)
    e.description = f"{member.mention} (`{member.id}`) was banned."
    e.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
    e.add_field(name="Moderator", value=str(moderator) if moderator else "Unknown", inline=True)
    e.add_field(name="Reason",    value=reason or "No reason provided", inline=False)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_unban(
    user: discord.User,
    moderator: discord.Member | None,
    reason: str | None,
) -> discord.Embed:
    e = _base("✅ Member Unbanned", 0x2ECC71)
    e.description = f"**{user}** (`{user.id}`) was unbanned."
    e.add_field(name="User",      value=f"{user} (`{user.id}`)", inline=True)
    e.add_field(name="Moderator", value=str(moderator) if moderator else "Unknown", inline=True)
    e.add_field(name="Reason",    value=reason or "No reason provided", inline=False)
    e.set_footer(text=f"User ID: {user.id}")
    e.set_thumbnail(url=_avatar_url(user))
    return e


def _embed_kick(
    member: discord.Member | discord.User,
    moderator: discord.Member | None,
    reason: str | None,
) -> discord.Embed:
    e = _base("👢 Member Kicked", 0xE67E22)
    e.description = f"**{member}** (`{member.id}`) was kicked."
    e.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
    e.add_field(name="Moderator", value=str(moderator) if moderator else "Unknown", inline=True)
    e.add_field(name="Reason",    value=reason or "No reason provided", inline=False)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_role_update(
    member: discord.Member,
    added: list[discord.Role],
    removed: list[discord.Role],
    moderator: discord.Member | None,
) -> discord.Embed:
    e = _base("🎭 Roles Updated", 0x9B59B6)
    e.description = f"{member.mention} (`{member.id}`)"
    if added:
        e.add_field(name="Roles Added",   value=" ".join(r.mention for r in added),   inline=False)
    if removed:
        e.add_field(name="Roles Removed", value=" ".join(r.mention for r in removed), inline=False)
    if moderator:
        e.add_field(name="By", value=moderator.mention, inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_nickname(
    member: discord.Member,
    before: str | None,
    after: str | None,
    moderator: discord.Member | None,
) -> discord.Embed:
    e = _base("✏️ Nickname Changed", 0x3498DB)
    e.description = f"{member.mention} (`{member.id}`)"
    e.add_field(name="Before", value=before or "*none*", inline=True)
    e.add_field(name="After",  value=after  or "*none*", inline=True)
    if moderator and moderator.id != member.id:
        e.add_field(name="Changed by", value=moderator.mention, inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_timeout(
    member: discord.Member,
    until: datetime | None,
    moderator: discord.Member | None,
    reason: str | None,
) -> discord.Embed:
    if until:
        e = _base("🔇 Member Timed Out", 0xF39C12)
        e.description = f"{member.mention} (`{member.id}`) was timed out."
        e.add_field(name="Expires",   value=_ts(until), inline=True)
        duration = until - _now()
        mins = int(duration.total_seconds() // 60)
        e.add_field(name="Duration",  value=f"{mins} minute(s)", inline=True)
    else:
        e = _base("🔊 Timeout Removed", 0x2ECC71)
        e.description = f"{member.mention} (`{member.id}`)'s timeout was removed."
    e.add_field(name="Moderator", value=str(moderator) if moderator else "Unknown", inline=True)
    e.add_field(name="Reason",    value=reason or "No reason provided", inline=False)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_username_change(
    member: discord.Member,
    before: str,
    after: str,
) -> discord.Embed:
    e = _base("👤 Username Changed", 0x1ABC9C)
    e.description = f"{member.mention} (`{member.id}`) changed their username."
    e.add_field(name="Before", value=before, inline=True)
    e.add_field(name="After",  value=after,  inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


def _embed_avatar_change(member: discord.Member, before_url: str | None) -> discord.Embed:
    e = _base("🖼️ Avatar Changed", 0x1ABC9C)
    e.description = f"{member.mention} (`{member.id}`) updated their avatar."
    e.set_thumbnail(url=_avatar_url(member))
    if before_url:
        e.set_image(url=before_url)
        e.add_field(name="Old Avatar", value=f"[Link]({before_url})", inline=True)
    e.add_field(name="New Avatar", value=f"[Link]({_avatar_url(member)})", inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    return e


# ─── Channels ─────────────────────────────────────────────────────────────────

def _embed_channel_create(channel: discord.abc.GuildChannel, moderator) -> discord.Embed:
    e = _base("📢 Channel Created", 0x2ECC71)
    e.add_field(name="Name",       value=channel.name,          inline=True)
    e.add_field(name="Type",       value=str(channel.type),     inline=True)
    e.add_field(name="Category",   value=str(channel.category) if hasattr(channel, "category") else "None", inline=True)
    e.add_field(name="Created by", value=str(moderator) if moderator else "Unknown", inline=True)
    e.set_footer(text=f"Channel ID: {channel.id}")
    return e


def _embed_channel_delete(channel: discord.abc.GuildChannel, moderator) -> discord.Embed:
    e = _base("🗑️ Channel Deleted", 0xE74C3C)
    e.add_field(name="Name",       value=channel.name,      inline=True)
    e.add_field(name="Type",       value=str(channel.type), inline=True)
    e.add_field(name="Deleted by", value=str(moderator) if moderator else "Unknown", inline=True)
    e.set_footer(text=f"Channel ID: {channel.id}")
    return e


def _embed_channel_update(
    before: discord.abc.GuildChannel,
    after: discord.abc.GuildChannel,
    moderator,
) -> discord.Embed:
    e = _base("🔧 Channel Updated", 0x3498DB)
    e.add_field(name="Channel",    value=after.mention if hasattr(after, "mention") else after.name, inline=True)
    e.add_field(name="Updated by", value=str(moderator) if moderator else "Unknown", inline=True)

    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if hasattr(before, "topic") and before.topic != after.topic:
        changes.append(f"**Topic:** `{before.topic or 'none'}` → `{after.topic or 'none'}`")
    if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
        changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
    if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
        changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
    if hasattr(before, "bitrate") and before.bitrate != after.bitrate:
        changes.append(f"**Bitrate:** `{before.bitrate}` → `{after.bitrate}`")
    if hasattr(before, "user_limit") and before.user_limit != after.user_limit:
        changes.append(f"**User Limit:** `{before.user_limit}` → `{after.user_limit}`")
    if before.category != after.category:
        changes.append(f"**Category:** `{before.category}` → `{after.category}`")

    if changes:
        e.add_field(name="Changes", value="\n".join(changes), inline=False)
    e.set_footer(text=f"Channel ID: {before.id}")
    return e


# ─── Roles ────────────────────────────────────────────────────────────────────

def _embed_role_create(role: discord.Role, moderator) -> discord.Embed:
    e = _base("✨ Role Created", 0x2ECC71)
    e.add_field(name="Name",       value=role.name,               inline=True)
    e.add_field(name="Color",      value=str(role.color),         inline=True)
    e.add_field(name="Mentionable", value=str(role.mentionable),  inline=True)
    e.add_field(name="Hoisted",    value=str(role.hoist),         inline=True)
    e.add_field(name="Created by", value=str(moderator) if moderator else "Unknown", inline=True)
    e.set_footer(text=f"Role ID: {role.id}")
    return e


def _embed_role_delete(role: discord.Role, moderator) -> discord.Embed:
    e = _base("🗑️ Role Deleted", 0xE74C3C)
    e.add_field(name="Name",       value=role.name,       inline=True)
    e.add_field(name="Color",      value=str(role.color), inline=True)
    e.add_field(name="Deleted by", value=str(moderator) if moderator else "Unknown", inline=True)
    e.set_footer(text=f"Role ID: {role.id}")
    return e


def _embed_role_edit(before: discord.Role, after: discord.Role, moderator) -> discord.Embed:
    e = _base("🔧 Role Updated", 0x3498DB)
    e.add_field(name="Role",       value=after.mention, inline=True)
    e.add_field(name="Updated by", value=str(moderator) if moderator else "Unknown", inline=True)

    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"**Color:** `{before.color}` → `{after.color}`")
    if before.hoist != after.hoist:
        changes.append(f"**Hoisted:** `{before.hoist}` → `{after.hoist}`")
    if before.mentionable != after.mentionable:
        changes.append(f"**Mentionable:** `{before.mentionable}` → `{after.mentionable}`")

    # permissions diff
    before_p = dict(before.permissions)
    after_p  = dict(after.permissions)
    gained = [p for p, v in after_p.items()  if v and not before_p.get(p)]
    lost   = [p for p, v in before_p.items() if v and not after_p.get(p)]
    if gained:
        changes.append("**Perms Gained:** " + ", ".join(f"`{p}`" for p in gained[:10]))
    if lost:
        changes.append("**Perms Lost:** "   + ", ".join(f"`{p}`" for p in lost[:10]))

    if changes:
        e.add_field(name="Changes", value="\n".join(changes), inline=False)
    e.set_footer(text=f"Role ID: {before.id}")
    return e


# ─── Voice ────────────────────────────────────────────────────────────────────

def _embed_voice(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> discord.Embed | None:
    # Determine what changed
    joined  = before.channel is None and after.channel is not None
    left    = before.channel is not None and after.channel is None
    moved   = before.channel and after.channel and before.channel.id != after.channel.id

    server_muted   = not before.mute         and after.mute
    server_unmuted = before.mute             and not after.mute
    server_deafed  = not before.deaf         and after.deaf
    server_undeafed= before.deaf             and not after.deaf
    self_muted     = not before.self_mute    and after.self_mute
    self_unmuted   = before.self_mute        and not after.self_mute
    self_deafed    = not before.self_deaf    and after.self_deaf
    self_undeafed  = before.self_deaf        and not after.self_deaf
    stream_start   = not before.self_stream  and after.self_stream
    stream_stop    = before.self_stream      and not after.self_stream
    video_start    = not before.self_video   and after.self_video
    video_stop     = before.self_video       and not after.self_video

    if joined:
        e = _base("🔊 Joined Voice", 0x2ECC71)
        e.description = f"{member.mention} joined **{after.channel.name}**."
    elif left:
        e = _base("🔇 Left Voice", 0xE74C3C)
        e.description = f"{member.mention} left **{before.channel.name}**."
    elif moved:
        e = _base("🔀 Moved Voice Channel", 0x3498DB)
        e.description = (
            f"{member.mention} moved from **{before.channel.name}** "
            f"→ **{after.channel.name}**."
        )
    else:
        # State changes only
        descriptions = []
        if server_muted:    descriptions.append("🔇 Server-muted")
        if server_unmuted:  descriptions.append("🔊 Server-unmuted")
        if server_deafed:   descriptions.append("🔕 Server-deafened")
        if server_undeafed: descriptions.append("🔔 Server-undeafened")
        if self_muted:      descriptions.append("🎙️ Self-muted")
        if self_unmuted:    descriptions.append("🎙️ Self-unmuted")
        if self_deafed:     descriptions.append("🎧 Self-deafened")
        if self_undeafed:   descriptions.append("🎧 Self-undeafened")
        if stream_start:    descriptions.append("📡 Started streaming")
        if stream_stop:     descriptions.append("📡 Stopped streaming")
        if video_start:     descriptions.append("📷 Camera on")
        if video_stop:      descriptions.append("📷 Camera off")

        if not descriptions:
            return None

        e = _base("🎙️ Voice State Changed", 0x9B59B6)
        e.description = f"{member.mention} in **{after.channel.name if after.channel else 'N/A'}**"
        e.add_field(name="Changes", value="\n".join(descriptions), inline=False)

    e.add_field(name="User", value=f"{member} (`{member.id}`)", inline=True)
    e.set_footer(text=f"User ID: {member.id}")
    e.set_thumbnail(url=_avatar_url(member))
    return e


# ─── Invites ─────────────────────────────────────────────────────────────────

def _embed_invite_create(invite: discord.Invite) -> discord.Embed:
    e = _base("🔗 Invite Created", 0x2ECC71)
    e.add_field(name="Code",       value=invite.code,                           inline=True)
    e.add_field(name="Channel",    value=invite.channel.mention if invite.channel else "Unknown", inline=True)
    e.add_field(name="Created by", value=str(invite.inviter) if invite.inviter else "Unknown", inline=True)
    e.add_field(name="Max Uses",   value=str(invite.max_uses) if invite.max_uses else "∞",     inline=True)
    e.add_field(name="Expires",    value=_ts(invite.expires_at) if invite.expires_at else "Never", inline=True)
    e.add_field(name="Temporary",  value=str(invite.temporary), inline=True)
    e.set_footer(text=f"Invite: {invite.url}")
    return e


def _embed_invite_delete(invite: discord.Invite) -> discord.Embed:
    e = _base("🔗 Invite Deleted", 0xE74C3C)
    e.add_field(name="Code",    value=invite.code,    inline=True)
    e.add_field(name="Channel", value=invite.channel.mention if invite.channel else "Unknown", inline=True)
    e.add_field(name="Uses",    value=str(invite.uses), inline=True)
    return e


# ─── Threads ──────────────────────────────────────────────────────────────────

def _embed_thread_create(thread: discord.Thread) -> discord.Embed:
    e = _base("🧵 Thread Created", 0x2ECC71)
    e.add_field(name="Name",    value=thread.name,             inline=True)
    e.add_field(name="Parent",  value=thread.parent.mention if thread.parent else "Unknown", inline=True)
    e.add_field(name="Owner",   value=f"<@{thread.owner_id}>", inline=True)
    e.set_footer(text=f"Thread ID: {thread.id}")
    return e


def _embed_thread_delete(thread: discord.Thread) -> discord.Embed:
    e = _base("🧵 Thread Deleted", 0xE74C3C)
    e.add_field(name="Name",   value=thread.name, inline=True)
    e.add_field(name="Parent", value=thread.parent.mention if thread.parent else "Unknown", inline=True)
    e.set_footer(text=f"Thread ID: {thread.id}")
    return e


def _embed_thread_update(before: discord.Thread, after: discord.Thread) -> discord.Embed | None:
    archived_now = not before.archived and after.archived
    unarchived   = before.archived and not after.archived
    locked_now   = not before.locked and after.locked

    if not (archived_now or unarchived or locked_now or before.name != after.name):
        return None

    e = _base("🧵 Thread Updated", 0x3498DB)
    e.add_field(name="Thread", value=after.mention, inline=True)
    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if archived_now:  changes.append("**Archived**")
    if unarchived:    changes.append("**Unarchived**")
    if locked_now:    changes.append("**Locked**")
    if changes:
        e.add_field(name="Changes", value="\n".join(changes), inline=False)
    e.set_footer(text=f"Thread ID: {before.id}")
    return e


# ─── Bot added ────────────────────────────────────────────────────────────────

def _embed_bot_add(member: discord.Member, moderator) -> discord.Embed:
    e = _base("🤖 Bot Added to Server", 0xF39C12)
    e.description  = f"**{member}** (`{member.id}`) was added."
    e.add_field(name="Bot",      value=f"{member.mention}", inline=True)
    e.add_field(name="Added by", value=str(moderator) if moderator else "Unknown", inline=True)
    e.set_thumbnail(url=_avatar_url(member))
    e.set_footer(text=f"Bot ID: {member.id}")
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# Cog
# ═══════════════════════════════════════════════════════════════════════════════

class LoggingCog(commands.Cog, name="Logging"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track previous display names / avatars for change detection
        self._prev_names: dict[int, str]   = {}
        self._prev_avatars: dict[int, str] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        key    = f"log_ch_{guild.id}"
        cached = guild_config_cache.get(key)
        if cached is not None:
            return guild.get_channel(cached)
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch_id = config["log_channel_id"]
            guild_config_cache.set(key, ch_id, ttl=120)
            return guild.get_channel(ch_id)
        return None

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed | None) -> None:
        if embed is None:
            return
        try:
            ch = await self._get_log_channel(guild)
            if ch and isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
        except Exception as exc:
            log.warning("_send_log: %s", exc)

    # ── Messages ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.guild.id != GUILD_ID:
            return
        if message.author.bot:
            return
        await self._send_log(message.guild, _embed_message_delete(message))

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild or guild.id != GUILD_ID:
            return
        channel = guild.get_channel(payload.channel_id)
        if channel:
            await self._send_log(guild, _embed_bulk_delete(channel, len(payload.message_ids)))

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.guild.id != GUILD_ID:
            return
        if before.author.bot:
            return
        if before.content == after.content:
            return
        await self._send_log(before.guild, _embed_message_edit(before, after))

    # ── Members ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        await db.ensure_user(member.id, member.guild.id)

        if member.bot:
            await asyncio.sleep(1)  # give audit log time to populate
            entry = await _fetch_audit(member.guild, discord.AuditLogAction.bot_add, member.id)
            moderator = entry.user if entry else None
            await self._send_log(member.guild, _embed_bot_add(member, moderator))
            return

        await self._send_log(member.guild, _embed_member_join(member))
        # Cache starting name/avatar for change tracking
        self._prev_names[member.id]   = member.name
        self._prev_avatars[member.id] = str(member.display_avatar)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        if member.bot:
            return

        # Small delay to let audit log settle (kick vs normal leave)
        await asyncio.sleep(1)
        entry = await _fetch_audit(member.guild, discord.AuditLogAction.kick, member.id)
        if entry:
            await self._send_log(
                member.guild,
                _embed_kick(member, entry.user, entry.reason),
            )
        else:
            await self._send_log(member.guild, _embed_member_leave(member))

        self._prev_names.pop(member.id, None)
        self._prev_avatars.pop(member.id, None)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        await asyncio.sleep(1)
        entry = await _fetch_audit(guild, discord.AuditLogAction.ban, user.id)
        moderator = entry.user   if entry else None
        reason    = entry.reason if entry else None
        await self._send_log(guild, _embed_ban(user, moderator, reason))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        await asyncio.sleep(1)
        entry = await _fetch_audit(guild, discord.AuditLogAction.unban, user.id)
        moderator = entry.user   if entry else None
        reason    = entry.reason if entry else None
        await self._send_log(guild, _embed_unban(user, moderator, reason))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.guild.id != GUILD_ID:
            return

        # ── Role changes ──
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            await asyncio.sleep(0.5)
            entry = await _fetch_audit(before.guild, discord.AuditLogAction.member_role_update, before.id)
            moderator = entry.user if entry else None
            await self._send_log(before.guild, _embed_role_update(after, added, removed, moderator))

        # ── Nickname changes ──
        if before.nick != after.nick:
            await asyncio.sleep(0.5)
            entry = await _fetch_audit(before.guild, discord.AuditLogAction.member_update, before.id)
            moderator = entry.user if entry else None
            await self._send_log(before.guild, _embed_nickname(after, before.nick, after.nick, moderator))

        # ── Timeout changes ──
        before_to = before.timed_out_until
        after_to  = after.timed_out_until
        if before_to != after_to:
            await asyncio.sleep(0.5)
            entry = await _fetch_audit(before.guild, discord.AuditLogAction.member_update, before.id)
            moderator = entry.user   if entry else None
            reason    = entry.reason if entry else None
            await self._send_log(before.guild, _embed_timeout(after, after_to, moderator, reason))

        # ── Username / avatar changes ──
        prev_name   = self._prev_names.get(before.id)
        prev_avatar = self._prev_avatars.get(before.id)

        if prev_name is not None and before.name != prev_name:
            await self._send_log(before.guild, _embed_username_change(after, prev_name, after.name))
            self._prev_names[before.id] = after.name

        curr_avatar = str(after.display_avatar)
        if prev_avatar is not None and curr_avatar != prev_avatar:
            await self._send_log(before.guild, _embed_avatar_change(after, prev_avatar))
            self._prev_avatars[before.id] = curr_avatar

    # ── Channels ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        moderator = entry.user if entry else None
        await self._send_log(channel.guild, _embed_channel_create(channel, moderator))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(channel.guild, discord.AuditLogAction.channel_delete)
        moderator = entry.user if entry else None
        await self._send_log(channel.guild, _embed_channel_delete(channel, moderator))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(before.guild, discord.AuditLogAction.channel_update, before.id)
        moderator = entry.user if entry else None
        await self._send_log(before.guild, _embed_channel_update(before, after, moderator))

    # ── Roles ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(role.guild, discord.AuditLogAction.role_create, role.id)
        moderator = entry.user if entry else None
        await self._send_log(role.guild, _embed_role_create(role, moderator))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(role.guild, discord.AuditLogAction.role_delete)
        moderator = entry.user if entry else None
        await self._send_log(role.guild, _embed_role_delete(role, moderator))

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.guild.id != GUILD_ID:
            return
        await asyncio.sleep(0.5)
        entry = await _fetch_audit(before.guild, discord.AuditLogAction.role_update, before.id)
        moderator = entry.user if entry else None
        embed = _embed_role_edit(before, after, moderator)
        # Only log if there are real changes
        if embed.fields and any(f.name == "Changes" for f in embed.fields):
            await self._send_log(before.guild, embed)
        elif len(embed.fields) <= 2:
            return  # nothing meaningful changed
        else:
            await self._send_log(before.guild, embed)

    # ── Voice ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.guild.id != GUILD_ID or member.bot:
            return
        embed = _embed_voice(member, before, after)
        await self._send_log(member.guild, embed)

    # ── Invites ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild or invite.guild.id != GUILD_ID:
            return
        await self._send_log(invite.guild, _embed_invite_create(invite))

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild or invite.guild.id != GUILD_ID:
            return
        await self._send_log(invite.guild, _embed_invite_delete(invite))

    # ── Threads ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.guild.id != GUILD_ID:
            return
        await self._send_log(thread.guild, _embed_thread_create(thread))

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        if thread.guild.id != GUILD_ID:
            return
        await self._send_log(thread.guild, _embed_thread_delete(thread))

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if before.guild.id != GUILD_ID:
            return
        embed = _embed_thread_update(before, after)
        await self._send_log(before.guild, embed)

    # ── Cache prime: load names/avatars on ready ──────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(GUILD_ID)
        if guild:
            for m in guild.members:
                self._prev_names[m.id]   = m.name
                self._prev_avatars[m.id] = str(m.display_avatar)
            log.info("LoggingCog: primed %d member name/avatar cache entries.", len(guild.members))


async def setup(bot: commands.Bot):
    await bot.add_cog(LoggingCog(bot))
