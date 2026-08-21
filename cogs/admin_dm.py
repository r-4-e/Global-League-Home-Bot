"""
cogs/admin_dm.py — Personal Admin DM System for GL Bot Owner.

Only the configured OWNER_ID can use this system.

Features:
- Bot DMs owner on startup with full server stats
- Owner can do all moderation via DM
- Owner can discuss GL suggestions/improvements with the bot
- Owner can query server stats anytime via DM
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

import config
from database import db

log = logging.getLogger("elura.admin_dm")

OWNER_ID = 1485610704441577552

# ── Suggestion discussion state ───────────────────────────────────────────────
# Tracks whether owner is in "suggestion mode" in DMs
_suggestion_sessions: dict[int, list[dict]] = {}


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def _mod_embed(title: str, color: discord.Color, **fields) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    for name, value in fields.items():
        embed.add_field(name=name.replace("_", " ").title(), value=str(value), inline=True)
    return embed


class AdminDM(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Startup DM ────────────────────────────────────────────────────────────
    async def send_startup_dm(self) -> None:
        await self.bot.wait_until_ready()
        owner = await self.bot.fetch_user(OWNER_ID)
        if owner is None:
            log.warning("Could not fetch owner for startup DM.")
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            await owner.send("✅ Bot is online. (Could not fetch guild stats.)")
            return

        # Gather stats
        total_members = guild.member_count or 0
        bots = sum(1 for m in guild.members if m.bot)
        humans = total_members - bots
        online = sum(
            1 for m in guild.members
            if m.status != discord.Status.offline and not m.bot
        )
        roles = len(guild.roles) - 1  # exclude @everyone
        channels = len(guild.channels)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        boosters = guild.premium_subscription_count or 0
        boost_level = guild.premium_tier
        created = guild.created_at.strftime("%d %b %Y")
        cogs_loaded = len(self.bot.cogs)
        commands_count = len(self.bot.commands)

        # DB stats
        active_cases = 0
        try:
            active_punishments = await db.get_active_timed_punishments(config.GUILD_ID)
            active_cases = len(active_punishments)
        except Exception as exc:
            log.warning("startup DM: could not fetch active punishments: %s", exc)
            active_cases = 0

        embed = discord.Embed(
            title="🟢 GL Bot is Online",
            description=f"**{guild.name}** is up and running.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        embed.add_field(name="👥 Total Members", value=str(total_members), inline=True)
        embed.add_field(name="🧑 Humans", value=str(humans), inline=True)
        embed.add_field(name="🤖 Bots", value=str(bots), inline=True)
        embed.add_field(name="🟢 Online", value=str(online), inline=True)
        embed.add_field(name="💬 Text Channels", value=str(text_channels), inline=True)
        embed.add_field(name="🔊 Voice Channels", value=str(voice_channels), inline=True)
        embed.add_field(name="🎭 Roles", value=str(roles), inline=True)
        embed.add_field(name="🚀 Boost Level", value=f"Level {boost_level} ({boosters} boosts)", inline=True)
        embed.add_field(name="📅 Server Created", value=created, inline=True)
        embed.add_field(name="⚙️ Cogs Loaded", value=str(cogs_loaded), inline=True)
        embed.add_field(name="📋 Commands", value=str(commands_count), inline=True)
        embed.add_field(name="⚠️ Active Punishments", value=str(active_cases), inline=True)

        embed.set_footer(text="DM me to manage GL • Type 'help' for DM commands")

        try:
            await owner.send(embed=embed)
            log.info("Startup DM sent to owner.")
        except discord.Forbidden:
            log.warning("Could not DM owner — DMs may be closed.")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        asyncio.create_task(self.send_startup_dm())

    # ── DM listener ───────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Only process DMs from owner
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != OWNER_ID:
            return
        if message.author.bot:
            return

        content = message.content.strip()
        lower = content.lower()

        # ── Help menu ─────────────────────────────────────────────────────────
        if lower in ("help", "commands", "menu"):
            await self._send_dm_help(message)
            return

        # ── Stats ─────────────────────────────────────────────────────────────
        if lower in ("stats", "status", "info"):
            await self._send_stats(message)
            return

        # ── Suggestion mode ───────────────────────────────────────────────────
        if lower.startswith("suggest ") or lower == "suggest":
            await self._handle_suggestion(message, content)
            return

        # ── Moderation commands ───────────────────────────────────────────────
        if lower.startswith("ban "):
            await self._handle_ban(message, content[4:].strip())
            return

        if lower.startswith("unban "):
            await self._handle_unban(message, content[6:].strip())
            return

        if lower.startswith("kick "):
            await self._handle_kick(message, content[5:].strip())
            return

        if lower.startswith("mute "):
            await self._handle_mute(message, content[5:].strip())
            return

        if lower.startswith("unmute "):
            await self._handle_unmute(message, content[7:].strip())
            return

        if lower.startswith("warn "):
            await self._handle_warn(message, content[5:].strip())
            return

        if lower.startswith("history "):
            await self._handle_history(message, content[8:].strip())
            return

        if lower.startswith("userinfo "):
            await self._handle_userinfo(message, content[9:].strip())
            return

        if lower.startswith("purge "):
            await self._handle_purge(message, content[6:].strip())
            return

        if lower.startswith("announce "):
            await self._handle_announce(message, content[9:].strip())
            return

        # ── Unknown ───────────────────────────────────────────────────────────
        await message.channel.send(
            "❓ Unknown command. Type `help` to see all DM commands."
        )

    # ── DM Help ───────────────────────────────────────────────────────────────
    async def _send_dm_help(self, message: discord.Message) -> None:
        embed = discord.Embed(
            title="🛡️ GL Admin DM Commands",
            description="Your personal admin interface. Everything stays in DMs.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="📊 Server",
            value=(
                "`stats` — Full server stats\n"
                "`userinfo <@user or ID>` — Member info\n"
                "`history <@user or ID>` — Mod history\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚖️ Moderation",
            value=(
                "`ban <ID> [reason]` — Ban a member\n"
                "`unban <ID> [reason]` — Unban a member\n"
                "`kick <ID> [reason]` — Kick a member\n"
                "`mute <ID> [duration] [reason]` — Timeout a member\n"
                "`unmute <ID>` — Remove timeout\n"
                "`warn <ID> [reason]` — Warn a member\n"
                "`purge <channel ID> <amount>` — Delete messages\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="📢 Server",
            value="`announce <channel ID> <message>` — Send announcement\n",
            inline=False,
        )
        embed.add_field(
            name="💡 GL Suggestions",
            value=(
                "`suggest <your idea>` — Discuss a GL idea\n"
                "Or just chat freely about what to add/remove/improve.\n"
            ),
            inline=False,
        )
        embed.set_footer(text="All actions are logged. Use member IDs for accuracy.")
        await message.channel.send(embed=embed)

    # ── Stats ─────────────────────────────────────────────────────────────────
    async def _send_stats(self, message: discord.Message) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            await message.channel.send("❌ Could not fetch guild.")
            return

        total_members = guild.member_count or 0
        bots = sum(1 for m in guild.members if m.bot)
        humans = total_members - bots
        online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
        idle = sum(1 for m in guild.members if m.status == discord.Status.idle and not m.bot)
        dnd = sum(1 for m in guild.members if m.status == discord.Status.dnd and not m.bot)
        offline = sum(1 for m in guild.members if m.status == discord.Status.offline and not m.bot)

        active_punishments = await db.get_active_timed_punishments(config.GUILD_ID)

        embed = discord.Embed(
            title=f"📊 {guild.name} — Live Stats",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="👥 Total", value=str(total_members), inline=True)
        embed.add_field(name="🧑 Humans", value=str(humans), inline=True)
        embed.add_field(name="🤖 Bots", value=str(bots), inline=True)
        embed.add_field(name="🟢 Online", value=str(online), inline=True)
        embed.add_field(name="🟡 Idle", value=str(idle), inline=True)
        embed.add_field(name="🔴 DND", value=str(dnd), inline=True)
        embed.add_field(name="⚫ Offline", value=str(offline), inline=True)
        embed.add_field(name="💬 Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="🎭 Roles", value=str(len(guild.roles) - 1), inline=True)
        embed.add_field(name="🚀 Boosts", value=f"{guild.premium_subscription_count} (Level {guild.premium_tier})", inline=True)
        embed.add_field(name="⚠️ Active Punishments", value=str(len(active_punishments)), inline=True)
        embed.add_field(name="⚙️ Cogs", value=str(len(self.bot.cogs)), inline=True)
        await message.channel.send(embed=embed)

    # ── Suggestion handler ────────────────────────────────────────────────────
    async def _handle_suggestion(self, message: discord.Message, content: str) -> None:
        idea = content[8:].strip() if content.lower().startswith("suggest ") else content[7:].strip()

        if not idea:
            await message.channel.send(
                "💡 What would you like to discuss?\n"
                "Just type your idea, e.g.:\n"
                "`suggest Add a weekly highlights channel`\n\n"
                "Or just chat freely — tell me what you want to add, remove, or improve in GL."
            )
            return

        # Build a thoughtful response about the suggestion
        await message.channel.send(
            f"💡 **GL Suggestion Noted:**\n> {idea}\n\n"
            f"Here's my take:\n"
            f"— Is this for the **bot**, the **server structure**, or **community events**?\n"
            f"— Tell me more and I can help you think through implementation.\n\n"
            f"Reply freely — I'm here to help you plan it out."
        )

    # ── Resolve member from ID or mention ────────────────────────────────────
    async def _resolve_member(self, guild: discord.Guild, raw: str) -> Optional[discord.Member]:
        raw = raw.strip().lstrip("<@!").rstrip(">")
        try:
            uid = int(raw)
            return guild.get_member(uid) or await guild.fetch_member(uid)
        except (ValueError, discord.NotFound, discord.HTTPException):
            return None

    async def _resolve_user(self, raw: str) -> Optional[discord.User]:
        raw = raw.strip().lstrip("<@!").rstrip(">")
        try:
            return await self.bot.fetch_user(int(raw))
        except (ValueError, discord.NotFound):
            return None

    # ── Ban ───────────────────────────────────────────────────────────────────
    async def _handle_ban(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        parts = args.split(maxsplit=1)
        if not parts:
            await message.channel.send("Usage: `ban <user ID> [reason]`")
            return

        member = await self._resolve_member(guild, parts[0])
        if member is None:
            user = await self._resolve_user(parts[0])
            if user is None:
                await message.channel.send("❌ User not found.")
                return

        reason = parts[1] if len(parts) > 1 else "Banned via owner DM"
        target = member or user

        try:
            await guild.ban(target, reason=f"[Owner DM] {reason}", delete_message_days=0)
            await db.create_case(
                user_id=target.id,
                moderator_id=OWNER_ID,
                action="ban",
                reason=reason,
                guild_id=config.GUILD_ID,
            )
            embed = _mod_embed(
                "🔨 Banned",
                discord.Color.red(),
                user=f"{target} (`{target.id}`)",
                reason=reason,
            )
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions to ban this user.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Unban ─────────────────────────────────────────────────────────────────
    async def _handle_unban(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        parts = args.split(maxsplit=1)
        if not parts:
            await message.channel.send("Usage: `unban <user ID> [reason]`")
            return

        user = await self._resolve_user(parts[0])
        if user is None:
            await message.channel.send("❌ User not found.")
            return

        reason = parts[1] if len(parts) > 1 else "Unbanned via owner DM"
        try:
            await guild.unban(user, reason=f"[Owner DM] {reason}")
            await db.create_case(
                user_id=user.id,
                moderator_id=OWNER_ID,
                action="unban",
                reason=reason,
                guild_id=config.GUILD_ID,
            )
            embed = _mod_embed(
                "✅ Unbanned",
                discord.Color.green(),
                user=f"{user} (`{user.id}`)",
                reason=reason,
            )
            await message.channel.send(embed=embed)
        except discord.NotFound:
            await message.channel.send("❌ That user isn't banned.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Kick ──────────────────────────────────────────────────────────────────
    async def _handle_kick(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        parts = args.split(maxsplit=1)
        if not parts:
            await message.channel.send("Usage: `kick <user ID> [reason]`")
            return

        member = await self._resolve_member(guild, parts[0])
        if member is None:
            await message.channel.send("❌ Member not found in server.")
            return

        reason = parts[1] if len(parts) > 1 else "Kicked via owner DM"
        try:
            await member.kick(reason=f"[Owner DM] {reason}")
            await db.create_case(
                user_id=member.id,
                moderator_id=OWNER_ID,
                action="kick",
                reason=reason,
                guild_id=config.GUILD_ID,
            )
            embed = _mod_embed(
                "👢 Kicked",
                discord.Color.orange(),
                user=f"{member} (`{member.id}`)",
                reason=reason,
            )
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions to kick this member.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Mute (timeout) ────────────────────────────────────────────────────────
    async def _handle_mute(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        parts = args.split(maxsplit=2)
        if not parts:
            await message.channel.send(
                "Usage: `mute <user ID> <duration> [reason]`\n"
                "Duration examples: `1h`, `30m`, `1d`, `7d`"
            )
            return

        member = await self._resolve_member(guild, parts[0])
        if member is None:
            await message.channel.send("❌ Member not found.")
            return

        # Parse duration
        duration_str = parts[1] if len(parts) > 1 else "1h"
        seconds = _parse_duration(duration_str)
        if seconds is None:
            await message.channel.send("❌ Invalid duration. Use `1h`, `30m`, `1d`, `7d` etc.")
            return

        reason = parts[2] if len(parts) > 2 else "Muted via owner DM"

        from datetime import timedelta
        until = discord.utils.utcnow() + timedelta(seconds=seconds)

        try:
            await member.timeout(until, reason=f"[Owner DM] {reason}")
            await db.create_case(
                user_id=member.id,
                moderator_id=OWNER_ID,
                action="mute",
                reason=reason,
                guild_id=config.GUILD_ID,
            )
            embed = _mod_embed(
                "🔇 Muted",
                discord.Color.orange(),
                user=f"{member} (`{member.id}`)",
                duration=duration_str,
                reason=reason,
            )
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions to timeout this member.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Unmute ────────────────────────────────────────────────────────────────
    async def _handle_unmute(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        member = await self._resolve_member(guild, args.split()[0] if args else "")
        if member is None:
            await message.channel.send("Usage: `unmute <user ID>`")
            return

        try:
            await member.timeout(None, reason="[Owner DM] Timeout removed")
            embed = _mod_embed(
                "🔊 Unmuted",
                discord.Color.green(),
                user=f"{member} (`{member.id}`)",
            )
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Warn ──────────────────────────────────────────────────────────────────
    async def _handle_warn(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        parts = args.split(maxsplit=1)
        if not parts:
            await message.channel.send("Usage: `warn <user ID> [reason]`")
            return

        member = await self._resolve_member(guild, parts[0])
        if member is None:
            await message.channel.send("❌ Member not found.")
            return

        reason = parts[1] if len(parts) > 1 else "Warned via owner DM"
        case_id = await db.create_case(
            user_id=member.id,
            moderator_id=OWNER_ID,
            action="warn",
            reason=reason,
            guild_id=config.GUILD_ID,
        )

        try:
            await member.send(
                f"⚠️ You have received a warning in **{guild.name}**.\n"
                f"**Reason:** {reason}"
            )
        except discord.Forbidden:
            pass

        embed = _mod_embed(
            "⚠️ Warned",
            discord.Color.yellow(),
            user=f"{member} (`{member.id}`)",
            reason=reason,
            case_id=str(case_id) if case_id else "N/A",
        )
        await message.channel.send(embed=embed)

    # ── History ───────────────────────────────────────────────────────────────
    async def _handle_history(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        raw = args.split()[0] if args else ""
        member = await self._resolve_member(guild, raw)
        user = member or await self._resolve_user(raw)

        if user is None:
            await message.channel.send("Usage: `history <user ID>`")
            return

        cases, total = await db.get_cases(user.id, guild_id=config.GUILD_ID)

        if not cases:
            await message.channel.send(f"✅ No cases found for {user}.")
            return

        embed = discord.Embed(
            title=f"📋 Mod History — {user}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.description = f"**Total cases:** {total}"

        for case in cases[:10]:
            ts = case.get("timestamp", "")[:10]
            embed.add_field(
                name=f"Case #{case['case_id']} — {case['action'].upper()} ({ts})",
                value=case.get("reason") or "No reason",
                inline=False,
            )

        await message.channel.send(embed=embed)

    # ── User info ─────────────────────────────────────────────────────────────
    async def _handle_userinfo(self, message: discord.Message, args: str) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        raw = args.split()[0] if args else ""
        member = await self._resolve_member(guild, raw)
        user = member or await self._resolve_user(raw)

        if user is None:
            await message.channel.send("Usage: `userinfo <user ID>`")
            return

        embed = discord.Embed(
            title=f"👤 {user}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=str(user.id), inline=True)
        embed.add_field(name="Bot", value="Yes" if user.bot else "No", inline=True)
        embed.add_field(
            name="Account Created",
            value=user.created_at.strftime("%d %b %Y"),
            inline=True,
        )

        if member:
            embed.add_field(
                name="Joined Server",
                value=member.joined_at.strftime("%d %b %Y") if member.joined_at else "Unknown",
                inline=True,
            )
            embed.add_field(
                name="Nickname",
                value=member.nick or "None",
                inline=True,
            )
            top_role = member.top_role
            embed.add_field(
                name="Top Role",
                value=top_role.mention if top_role.name != "@everyone" else "None",
                inline=True,
            )
            embed.add_field(
                name="Status",
                value=str(member.status).title(),
                inline=True,
            )
            timed_out = member.is_timed_out()
            embed.add_field(name="Timed Out", value="Yes" if timed_out else "No", inline=True)

        cases, total = await db.get_cases(user.id, guild_id=config.GUILD_ID)
        embed.add_field(name="Total Cases", value=str(total), inline=True)

        await message.channel.send(embed=embed)

    # ── Purge ─────────────────────────────────────────────────────────────────
    async def _handle_purge(self, message: discord.Message, args: str) -> None:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `purge <channel ID> <amount>`")
            return

        try:
            channel_id = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            await message.channel.send("❌ Invalid channel ID or amount.")
            return

        if amount < 1 or amount > 100:
            await message.channel.send("❌ Amount must be between 1 and 100.")
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await message.channel.send("❌ Channel not found.")
            return

        try:
            deleted = await channel.purge(limit=amount)
            await message.channel.send(f"✅ Deleted {len(deleted)} messages in {channel.mention}.")
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions to purge that channel.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")

    # ── Announce ──────────────────────────────────────────────────────────────
    async def _handle_announce(self, message: discord.Message, args: str) -> None:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `announce <channel ID> <message>`")
            return

        try:
            channel_id = int(parts[0])
        except ValueError:
            await message.channel.send("❌ Invalid channel ID.")
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await message.channel.send("❌ Channel not found.")
            return

        announcement = parts[1]
        try:
            await channel.send(announcement)
            await message.channel.send(f"✅ Announced in {channel.mention}.")
        except discord.Forbidden:
            await message.channel.send("❌ Missing permissions to send in that channel.")
        except discord.HTTPException as e:
            await message.channel.send(f"❌ Failed: {e}")


# ── Duration parser ───────────────────────────────────────────────────────────
def _parse_duration(s: str) -> Optional[int]:
    """Parse duration strings like 1h, 30m, 1d, 7d into seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    s = s.strip().lower()
    if s[-1] in units:
        try:
            return int(s[:-1]) * units[s[-1]]
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminDM(bot))
