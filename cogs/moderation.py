"""
cogs/moderation.py — Moderation commands for Global League Bot.
Prefix: gl.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils import embeds
from utils.permissions import gate_hierarchy, gate_permission, gate_warn

log = logging.getLogger(__name__)


async def _log_action(bot, guild, embed):
    try:
        cfg = await db.get_guild_config(guild.id)
        if cfg and cfg.get("log_channel_id"):
            ch = guild.get_channel(cfg["log_channel_id"])
            if ch and isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
    except Exception as exc:
        log.warning("_log_action failed: %s", exc)


async def _dm_user(user, embed):
    try:
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def _create_and_log(bot, guild, *, user, moderator, action, reason,
                           expires_at=None, extra_data=None, extra_fields=None):
    await db.ensure_user(user.id, guild.id)
    case_id = await db.create_case(
        user_id=user.id, moderator_id=moderator.id, action=action,
        reason=reason, expires_at=expires_at, extra_data=extra_data, guild_id=guild.id,
    )
    log_embed = embeds.moderation_action(
        action=action, user=user, moderator=moderator,
        reason=reason, case_id=case_id, extra_fields=extra_fields,
    )
    await _log_action(bot, guild, log_embed)
    return case_id


def _parse_duration(s: str) -> Optional[timedelta]:
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if not s:
        return None
    unit = s[-1].lower()
    if unit not in unit_map:
        return None
    try:
        return timedelta(seconds=int(s[:-1]) * unit_map[unit])
    except ValueError:
        return None


class ModerationCog(commands.Cog, name="Moderation"):

    def __init__(self, bot):
        self.bot = bot

    # ── warn ──────────────────────────────────────────────────────────────

    @commands.command(name="warn")
    @commands.guild_only()
    async def warn(self, ctx, user: discord.Member, *, reason: str = None):
        """Warn a member. Requires Warn Role."""
        if not await gate_warn(ctx): return
        if not await gate_hierarchy(ctx, user): return

        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="WARN", reason=reason)

        # Threshold check
        all_cases, _ = await db.get_cases(user.id, ctx.guild.id, page=1, page_size=500)
        warn_count   = sum(1 for c in all_cases if c.get("action") == "WARN" and c.get("active"))
        from cogs.warn_threshold import apply_threshold
        threshold_result = await apply_threshold(self.bot, ctx.guild, user, warn_count)

        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name,
                        action="Warning", reason=reason, case_id=case_id))

        desc = f"{user.mention} warned. Case #{case_id} — Total warns: **{warn_count}**"
        if threshold_result:
            desc += f"\n⚒️ Threshold triggered: {threshold_result}"
        await ctx.send(embed=embeds.success("Warning Issued", desc))

    @commands.command(name="unwarn")
    @commands.guild_only()
    async def unwarn(self, ctx, case_id: int):
        """Remove a warning by case ID. Requires Warn Role."""
        if not await gate_warn(ctx): return
        ok = await db.deactivate_case(case_id)
        if ok:
            await ctx.send(embed=embeds.success("Warning Removed", f"Case #{case_id} removed."))
        else:
            await ctx.send(embed=embeds.error("Not Found", f"Case #{case_id} not found."))

    @commands.command(name="history")
    @commands.guild_only()
    async def history(self, ctx, user: discord.Member, page: int = 1):
        """View moderation history for a user. Requires Warn Role."""
        if not await gate_warn(ctx): return
        from config import HISTORY_PAGE_SIZE
        cases, total = await db.get_cases(user.id, ctx.guild.id, page, HISTORY_PAGE_SIZE)
        total_pages  = max(1, -(-total // HISTORY_PAGE_SIZE))
        if not cases:
            await ctx.send(embed=embeds.info("No History", f"No history found for {user.mention}."))
            return
        await ctx.send(embed=embeds.case_list(user, cases, page, total_pages))

    @commands.command(name="note_add")
    @commands.guild_only()
    async def note_add(self, ctx, user: discord.Member, *, content: str):
        """Add a staff note to a user."""
        if not await gate_warn(ctx): return
        await db.ensure_user(user.id, ctx.guild.id)
        note_id = await db.add_note(user_id=user.id, moderator_id=ctx.author.id,
                                     content=content, guild_id=ctx.guild.id)
        if note_id:
            await ctx.send(embed=embeds.success("Note Added", f"Note #{note_id} added to {user.mention}."))
        else:
            await ctx.send(embed=embeds.error("Failed", "Could not save note."))

    @commands.command(name="note_list")
    @commands.guild_only()
    async def note_list(self, ctx, user: discord.Member):
        """View staff notes for a user."""
        if not await gate_warn(ctx): return
        notes = await db.get_notes(user.id, ctx.guild.id)
        if not notes:
            await ctx.send(embed=embeds.info("No Notes", f"No notes for {user.mention}."))
            return
        e = discord.Embed(title=f"📝 Notes — {user}", color=0x3498DB)
        for note in notes[:10]:
            ts = note.get("timestamp", "")[:10]
            e.add_field(name=f"#{note['note_id']} ({ts})",
                        value=f"{note['content'][:200]}\n*— <@{note['moderator_id']}>*", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="note_delete")
    @commands.guild_only()
    async def note_delete(self, ctx, note_id: int):
        """Delete a staff note by ID."""
        if not await gate_warn(ctx): return
        ok = await db.delete_note(note_id)
        if ok:
            await ctx.send(embed=embeds.success("Note Deleted", f"Note #{note_id} deleted."))
        else:
            await ctx.send(embed=embeds.error("Failed", f"Could not delete note #{note_id}."))

    # ── mute ──────────────────────────────────────────────────────────────

    @commands.command(name="mute")
    @commands.guild_only()
    async def mute(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """Mute a member using the muted role. Duration: 10m, 2h, 1d"""
        if not await gate_permission(ctx, "mute_members"): return
        if not await gate_hierarchy(ctx, user): return

        cfg = await db.get_guild_config(ctx.guild.id)
        muted_role_id = cfg.get("muted_role_id") if cfg else None
        if not muted_role_id:
            await ctx.send(embed=embeds.error("No Muted Role", "Run gl.setup first.")); return

        muted_role = ctx.guild.get_role(muted_role_id)
        if not muted_role:
            await ctx.send(embed=embeds.error("Role Not Found", "Muted role no longer exists.")); return

        expires_at = None
        if duration:
            td = _parse_duration(duration)
            if td is None:
                await ctx.send(embed=embeds.error("Invalid Duration", "Use `10m`, `2h`, `1d`.")); return
            expires_at = datetime.now(timezone.utc) + td

        try:
            await user.add_roles(muted_role, reason=f"Muted by {ctx.author}: {reason}")
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("No Permission", "I can't add that role.")); return

        extra = [("Expires", f"<t:{int(expires_at.timestamp())}:R>", True)] if expires_at else []
        case_id = await _create_and_log(self.bot, ctx.guild, user=user, moderator=ctx.author,
                    action="MUTE", reason=reason, expires_at=expires_at,
                    extra_data={"muted_role_id": muted_role_id}, extra_fields=extra)
        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name, action="Mute",
                        reason=reason, case_id=case_id,
                        extra=f"**Duration:** {duration or 'Permanent'}"))
        await ctx.send(embed=embeds.success("Member Muted", f"{user.mention} muted. Case #{case_id}"))

    @commands.command(name="unmute")
    @commands.guild_only()
    async def unmute(self, ctx, user: discord.Member, *, reason: str = None):
        """Remove mute from a member."""
        if not await gate_permission(ctx, "mute_members"): return
        cfg = await db.get_guild_config(ctx.guild.id)
        muted_role_id = cfg.get("muted_role_id") if cfg else None
        if muted_role_id:
            muted_role = ctx.guild.get_role(muted_role_id)
            if muted_role and muted_role in user.roles:
                await user.remove_roles(muted_role, reason=f"Unmuted by {ctx.author}: {reason}")
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="UNMUTE", reason=reason)
        await ctx.send(embed=embeds.success("Member Unmuted", f"{user.mention} unmuted. Case #{case_id}"))

    # ── timeout ───────────────────────────────────────────────────────────

    @commands.command(name="timeout")
    @commands.guild_only()
    async def timeout(self, ctx, user: discord.Member, duration: str = "10m", *, reason: str = None):
        """Timeout a member. Duration: 10m, 2h, 1d (max 28d)"""
        if not await gate_permission(ctx, "moderate_members"): return
        if not await gate_hierarchy(ctx, user): return
        td = _parse_duration(duration)
        if td is None:
            await ctx.send(embed=embeds.error("Invalid Duration", "Use `10m`, `2h`, `1d`.")); return
        if td.total_seconds() > 28 * 86400:
            await ctx.send(embed=embeds.error("Too Long", "Max timeout is 28 days.")); return
        try:
            await user.timeout(discord.utils.utcnow() + td, reason=reason)
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "I couldn't timeout that user.")); return
        expires_at = datetime.now(timezone.utc) + td
        case_id = await _create_and_log(self.bot, ctx.guild, user=user, moderator=ctx.author,
                    action="TIMEOUT", reason=reason, expires_at=expires_at,
                    extra_fields=[("Duration", duration, True)])
        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name, action="Timeout",
                        reason=reason, case_id=case_id, extra=f"**Duration:** {duration}"))
        await ctx.send(embed=embeds.success("Timeout Applied", f"{user.mention} timed out for {duration}. Case #{case_id}"))

    @commands.command(name="untimeout")
    @commands.guild_only()
    async def untimeout(self, ctx, user: discord.Member, *, reason: str = None):
        """Remove a timeout from a member."""
        if not await gate_permission(ctx, "moderate_members"): return
        try:
            await user.timeout(None, reason=reason)
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "Could not remove timeout.")); return
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="UNTIMEOUT", reason=reason)
        await ctx.send(embed=embeds.success("Timeout Removed", f"{user.mention}'s timeout removed. Case #{case_id}"))

    # ── kick ──────────────────────────────────────────────────────────────

    @commands.command(name="kick")
    @commands.guild_only()
    async def kick(self, ctx, user: discord.Member, *, reason: str = None):
        """Kick a member from the server."""
        if not await gate_permission(ctx, "kick_members"): return
        if not await gate_hierarchy(ctx, user): return
        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name, action="Kick", reason=reason))
        try:
            await ctx.guild.kick(user, reason=reason)
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "I couldn't kick that user.")); return
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="KICK", reason=reason)
        await ctx.send(embed=embeds.success("Member Kicked", f"{user} was kicked. Case #{case_id}"))

    # ── ban ───────────────────────────────────────────────────────────────

    @commands.command(name="ban")
    @commands.guild_only()
    async def ban(self, ctx, user: discord.Member, delete_days: int = 0, *, reason: str = None):
        """Ban a member. Usage: gl.ban @user [delete_days] [reason]"""
        if not await gate_permission(ctx, "ban_members"): return
        if not await gate_hierarchy(ctx, user): return
        delete_days = max(0, min(7, delete_days))
        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name, action="Ban", reason=reason))
        try:
            await ctx.guild.ban(user, reason=f"Banned by {ctx.author}: {reason}",
                                delete_message_days=delete_days)
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "I couldn't ban that user.")); return
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="BAN", reason=reason)
        await ctx.send(embed=embeds.success("Member Banned", f"{user} was banned. Case #{case_id}"))

    @commands.command(name="unban")
    @commands.guild_only()
    async def unban(self, ctx, user_id: int, *, reason: str = None):
        """Unban a user by ID. Usage: gl.unban <user_id> [reason]"""
        if not await gate_permission(ctx, "ban_members"): return
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            await ctx.send(embed=embeds.error("Not Found", "That user is not banned or doesn't exist.")); return
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "I couldn't unban that user.")); return
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="UNBAN", reason=reason)
        await ctx.send(embed=embeds.success("User Unbanned", f"{user} was unbanned. Case #{case_id}"))

    @commands.command(name="softban")
    @commands.guild_only()
    async def softban(self, ctx, user: discord.Member, *, reason: str = None):
        """Ban + unban to delete recent messages."""
        if not await gate_permission(ctx, "ban_members"): return
        if not await gate_hierarchy(ctx, user): return
        await _dm_user(user, embeds.user_dm(guild_name=ctx.guild.name, action="Softban", reason=reason))
        try:
            await ctx.guild.ban(user, reason=reason, delete_message_days=7)
            await ctx.guild.unban(user, reason="Softban — auto-unban")
        except discord.Forbidden:
            await ctx.send(embed=embeds.error("Failed", "I couldn't softban that user.")); return
        case_id = await _create_and_log(self.bot, ctx.guild, user=user,
                    moderator=ctx.author, action="SOFTBAN", reason=reason)
        await ctx.send(embed=embeds.success("Member Softbanned", f"{user} softbanned. Case #{case_id}"))

    @commands.command(name="massban")
    @commands.guild_only()
    async def massban(self, ctx, *, args: str):
        """Ban multiple users. Usage: gl.massban id1,id2,id3 reason"""
        if not await gate_permission(ctx, "ban_members"): return
        parts   = args.split(maxsplit=1)
        ids_str = parts[0]
        reason  = parts[1] if len(parts) > 1 else None
        ids     = [s.strip() for s in ids_str.split(",") if s.strip()]
        success_list, failed_list = [], []
        async with ctx.typing():
            for raw_id in ids:
                try:
                    uid  = int(raw_id)
                    user = await self.bot.fetch_user(uid)
                    await ctx.guild.ban(user, reason=f"Massbanned by {ctx.author}: {reason}")
                    await _create_and_log(self.bot, ctx.guild, user=user,
                                moderator=ctx.author, action="MASSBAN", reason=reason)
                    success_list.append(str(uid))
                    await asyncio.sleep(0.5)
                except Exception as exc:
                    log.warning("massban %s: %s", raw_id, exc)
                    failed_list.append(raw_id)
        desc = f"**Banned ({len(success_list)}):** {', '.join(success_list) or 'none'}"
        if failed_list:
            desc += f"\n**Failed ({len(failed_list)}):** {', '.join(failed_list)}"
        await ctx.send(embed=embeds.success("Mass Ban Complete", desc))

    @commands.command(name="masskick")
    @commands.guild_only()
    async def masskick(self, ctx, *, args: str):
        """Kick multiple members. Usage: gl.masskick id1,id2,id3 reason"""
        if not await gate_permission(ctx, "kick_members"): return
        parts   = args.split(maxsplit=1)
        ids_str = parts[0]
        reason  = parts[1] if len(parts) > 1 else None
        ids     = [s.strip() for s in ids_str.split(",") if s.strip()]
        success_list, failed_list = [], []
        async with ctx.typing():
            for raw_id in ids:
                try:
                    uid    = int(raw_id)
                    member = ctx.guild.get_member(uid)
                    if not member:
                        failed_list.append(raw_id); continue
                    await ctx.guild.kick(member, reason=reason)
                    await _create_and_log(self.bot, ctx.guild, user=member,
                                moderator=ctx.author, action="MASSKICK", reason=reason)
                    success_list.append(str(uid))
                    await asyncio.sleep(0.5)
                except Exception as exc:
                    log.warning("masskick %s: %s", raw_id, exc)
                    failed_list.append(raw_id)
        desc = f"**Kicked ({len(success_list)}):** {', '.join(success_list) or 'none'}"
        if failed_list:
            desc += f"\n**Failed ({len(failed_list)}):** {', '.join(failed_list)}"
        await ctx.send(embed=embeds.success("Mass Kick Complete", desc))

    # ── channel commands ──────────────────────────────────────────────────

    @commands.command(name="clear")
    @commands.guild_only()
    async def clear(self, ctx, amount: int, user: discord.Member = None):
        """Bulk delete messages. Usage: gl.clear <amount> [@user]"""
        if not await gate_permission(ctx, "manage_messages"): return
        amount = max(1, min(100, amount))
        await ctx.message.delete()
        check   = (lambda m: m.author.id == user.id) if user else None
        deleted = await ctx.channel.purge(limit=amount, check=check)
        await ctx.send(embed=embeds.success("Cleared", f"Deleted **{len(deleted)}** messages."),
                       delete_after=5)

    @commands.command(name="slowmode")
    @commands.guild_only()
    async def slowmode(self, ctx, seconds: int, channel: discord.TextChannel = None):
        """Set slowmode. Usage: gl.slowmode <seconds> [#channel]"""
        if not await gate_permission(ctx, "manage_channels"): return
        target  = channel or ctx.channel
        seconds = max(0, min(21600, seconds))
        await target.edit(slowmode_delay=seconds)
        msg = f"Slowmode {'disabled' if seconds == 0 else f'set to {seconds}s'} in {target.mention}"
        await ctx.send(embed=embeds.success("Slowmode Updated", msg))

    @commands.command(name="lock")
    @commands.guild_only()
    async def lock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
        """Lock a channel."""
        if not await gate_permission(ctx, "manage_channels"): return
        target  = channel or ctx.channel
        everyone = ctx.guild.default_role
        await target.set_permissions(everyone, send_messages=False, reason=reason)
        await target.send(embed=embeds.warning("Channel Locked",
                f"This channel has been locked. Reason: {reason or 'N/A'}"))
        await ctx.send(embed=embeds.success("Channel Locked", f"{target.mention} is now locked."))

    @commands.command(name="unlock")
    @commands.guild_only()
    async def unlock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
        """Unlock a channel."""
        if not await gate_permission(ctx, "manage_channels"): return
        target   = channel or ctx.channel
        everyone = ctx.guild.default_role
        await target.set_permissions(everyone, send_messages=None, reason=reason)
        await target.send(embed=embeds.success("Channel Unlocked", "This channel has been unlocked."))
        await ctx.send(embed=embeds.success("Channel Unlocked", f"{target.mention} is now unlocked."))

    @commands.command(name="nick")
    @commands.guild_only()
    async def nick(self, ctx, user: discord.Member, *, nickname: str = None):
        """Change or reset a member's nickname."""
        if not await gate_permission(ctx, "manage_nicknames"): return
        if not await gate_hierarchy(ctx, user): return
        old = user.display_name
        await user.edit(nick=nickname)
        await ctx.send(embed=embeds.success("Nickname Updated",
                f"`{old}` → `{nickname or 'reset'}`"))

    @commands.command(name="giverole")
    @commands.guild_only()
    async def giverole(self, ctx, role: discord.Role):
        """[Owner only] Give yourself any role below the bot's top role.
        Usage: gl.giverole @role"""
        from utils.permissions import BOT_OWNER_ID
        if ctx.author.id != BOT_OWNER_ID:
            await ctx.send("❌ This command is restricted to the bot owner."); return

        bot_top = ctx.guild.me.top_role
        if role >= bot_top:
            await ctx.send(f"❌ **{role.name}** is above or equal to my top role. Move my role higher first."); return
        if role in ctx.author.roles:
            await ctx.send(f"❌ You already have **{role.name}**."); return

        try:
            await ctx.author.add_roles(role, reason="Owner self-role assignment")
            await ctx.send(embed=embeds.success("Role Added", f"{role.mention} added to you."))
        except discord.Forbidden:
            await ctx.send("❌ Discord prevented this. Make sure my role is above the target role.")

    @commands.command(name="takerole")
    @commands.guild_only()
    async def takerole(self, ctx, role: discord.Role):
        """[Owner only] Remove any role from yourself.
        Usage: gl.takerole @role"""
        from utils.permissions import BOT_OWNER_ID
        if ctx.author.id != BOT_OWNER_ID:
            await ctx.send("❌ This command is restricted to the bot owner."); return
        if role not in ctx.author.roles:
            await ctx.send(f"❌ You don't have **{role.name}**."); return
        try:
            await ctx.author.remove_roles(role, reason="Owner self-role removal")
            await ctx.send(embed=embeds.success("Role Removed", f"{role.mention} removed from you."))
        except discord.Forbidden:
            await ctx.send("❌ Discord prevented this.")


        """Add a role to a member."""
        if not await gate_permission(ctx, "manage_roles"): return
        if not await gate_hierarchy(ctx, user): return
        if role in user.roles:
            await ctx.send(embed=embeds.warning("Already Has Role",
                    f"{user.mention} already has {role.mention}.")); return
        await user.add_roles(role, reason=reason)
        await ctx.send(embed=embeds.success("Role Added", f"{role.mention} added to {user.mention}."))

    @commands.command(name="role_remove")
    @commands.guild_only()
    async def role_remove(self, ctx, user: discord.Member, role: discord.Role, *, reason: str = None):
        """Remove a role from a member."""
        if not await gate_permission(ctx, "manage_roles"): return
        if not await gate_hierarchy(ctx, user): return
        if role not in user.roles:
            await ctx.send(embed=embeds.warning("Doesn't Have Role",
                    f"{user.mention} doesn't have {role.mention}.")); return
        await user.remove_roles(role, reason=reason)
        await ctx.send(embed=embeds.success("Role Removed", f"{role.mention} removed from {user.mention}."))

    @commands.command(name="nuke")
    @commands.guild_only()
    async def nuke(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
        """Delete and recreate a channel instantly."""
        if not await gate_permission(ctx, "manage_channels"): return
        target   = channel or ctx.channel
        position = target.position
        new_ch   = await target.clone(reason=f"Nuked by {ctx.author}: {reason}")
        await new_ch.edit(position=position)
        await target.delete(reason=f"Nuked by {ctx.author}")
        await new_ch.send(embed=embeds.success("Channel Nuked",
                f"This channel was nuked by {ctx.author.mention}."))


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
