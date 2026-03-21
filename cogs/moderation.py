"""
cogs/moderation.py — Full moderation command suite for Elura.

Every command:
  1. Checks permissions via the middleware layer
  2. Enforces role hierarchy
  3. Creates a case in the database
  4. DMs the target user
  5. Logs the action to the log channel
  6. Responds ephemerally to the moderator
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils import embeds
from utils.permissions import (
    gate_hierarchy,
    gate_permission,
    gate_warn,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _log_action(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> None:
    """Send embed to the configured log channel."""
    try:
        config = await db.get_guild_config(guild.id)
        if config and config.get("log_channel_id"):
            ch = guild.get_channel(config["log_channel_id"])
            if ch and isinstance(ch, discord.TextChannel):
                await ch.send(embed=embed)
    except Exception as exc:
        log.warning("_log_action failed: %s", exc)


async def _dm_user(
    user: discord.User | discord.Member,
    embed: discord.Embed,
) -> None:
    try:
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass  # DMs disabled — silently ignore


async def _create_and_log(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    user: discord.User | discord.Member,
    moderator: discord.User | discord.Member,
    action: str,
    reason: Optional[str],
    expires_at: Optional[datetime] = None,
    extra_data: Optional[dict] = None,
    extra_fields: Optional[list] = None,
) -> int | None:
    """Create a case, send log embed, return case_id."""
    await db.ensure_user(user.id, guild.id)
    case_id = await db.create_case(
        user_id=user.id,
        moderator_id=moderator.id,
        action=action,
        reason=reason,
        expires_at=expires_at,
        extra_data=extra_data,
        guild_id=guild.id,
    )
    log_embed = embeds.moderation_action(
        action=action,
        user=user,
        moderator=moderator,
        reason=reason,
        case_id=case_id,
        extra_fields=extra_fields,
    )
    await _log_action(bot, guild, log_embed)
    return case_id


def _parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a human duration string like '10m', '2h', '1d' into a timedelta.
    Returns None on invalid input.
    """
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if not duration_str:
        return None
    unit = duration_str[-1].lower()
    if unit not in unit_map:
        return None
    try:
        amount = int(duration_str[:-1])
    except ValueError:
        return None
    return timedelta(seconds=amount * unit_map[unit])


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ModerationCog(commands.Cog, name="Moderation"):
    """All moderation slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._guild = discord.Object(id=GUILD_ID)

    # ── /warn ─────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(user="Member to warn", reason="Reason for warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_warn(interaction):
            return
        if not await gate_hierarchy(interaction, user):
            return

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="WARN", reason=reason,
        )
        await _dm_user(
            user,
            embeds.user_dm(
                guild_name=interaction.guild.name,
                action="Warning",
                reason=reason,
                case_id=case_id,
            ),
        )
        await interaction.response.send_message(
            embed=embeds.success(
                "Warning Issued",
                f"{user.mention} has been warned. Case #{case_id}",
            ),
            ephemeral=True,
        )

    # ── /unwarn ───────────────────────────────────────────────────────────

    @app_commands.command(name="unwarn", description="Remove a warning by case ID.")
    @app_commands.describe(case_id="The case ID to remove")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unwarn(
        self,
        interaction: discord.Interaction,
        case_id: int,
    ) -> None:
        if not await gate_warn(interaction):
            return
        ok = await db.deactivate_case(case_id)
        if ok:
            await interaction.response.send_message(
                embed=embeds.success("Warning Removed", f"Case #{case_id} has been removed."),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error("Not Found", f"Case #{case_id} not found."),
                ephemeral=True,
            )

    # ── /history ──────────────────────────────────────────────────────────

    @app_commands.command(name="history", description="View moderation history for a user.")
    @app_commands.describe(user="Target user", page="Page number (default 1)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def history(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        page: int = 1,
    ) -> None:
        if not await gate_warn(interaction):
            return
        from config import HISTORY_PAGE_SIZE
        cases, total = await db.get_cases(user.id, interaction.guild.id, page, HISTORY_PAGE_SIZE)
        total_pages = max(1, -(-total // HISTORY_PAGE_SIZE))  # ceiling div

        if not cases:
            await interaction.response.send_message(
                embed=embeds.info("No History", f"No moderation history found for {user.mention}."),
                ephemeral=True,
            )
            return

        view = HistoryPaginator(
            bot=self.bot,
            user=user,
            guild_id=interaction.guild.id,
            current_page=page,
            total_pages=total_pages,
            cases=cases,
        )
        await interaction.response.send_message(
            embed=embeds.case_list(user, cases, page, total_pages),
            view=view,
            ephemeral=True,
        )

    # ── /mute ─────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Mute a member using the muted role.")
    @app_commands.describe(
        user="Member to mute",
        reason="Reason",
        duration="Duration e.g. 10m, 2h, 1d (omit for permanent)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
        duration: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "mute_members"):
            return
        if not await gate_hierarchy(interaction, user):
            return

        config = await db.get_guild_config(interaction.guild.id)
        muted_role_id = config.get("muted_role_id") if config else None
        if not muted_role_id:
            await interaction.response.send_message(
                embed=embeds.error("No Muted Role", "Muted role not configured. Use /setup."),
                ephemeral=True,
            )
            return

        muted_role = interaction.guild.get_role(muted_role_id)
        if not muted_role:
            await interaction.response.send_message(
                embed=embeds.error("Role Not Found", "Muted role no longer exists."),
                ephemeral=True,
            )
            return

        expires_at = None
        if duration:
            td = _parse_duration(duration)
            if td is None:
                await interaction.response.send_message(
                    embed=embeds.error("Invalid Duration", "Use formats like `10m`, `2h`, `1d`."),
                    ephemeral=True,
                )
                return
            expires_at = datetime.now(timezone.utc) + td

        try:
            await user.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("No Permission", "I can't add that role."),
                ephemeral=True,
            )
            return

        extra = []
        if expires_at:
            extra = [("Expires", f"<t:{int(expires_at.timestamp())}:R>", True)]

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="MUTE", reason=reason,
            expires_at=expires_at,
            extra_data={"muted_role_id": muted_role_id},
            extra_fields=extra,
        )
        await _dm_user(user, embeds.user_dm(
            guild_name=interaction.guild.name,
            action="Mute",
            reason=reason,
            case_id=case_id,
            extra=f"**Duration:** {duration or 'Permanent'}",
        ))
        await interaction.response.send_message(
            embed=embeds.success("Member Muted", f"{user.mention} muted. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /unmute ───────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Remove mute from a member.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "mute_members"):
            return

        config = await db.get_guild_config(interaction.guild.id)
        muted_role_id = config.get("muted_role_id") if config else None
        if not muted_role_id:
            await interaction.response.send_message(
                embed=embeds.error("No Muted Role", "Muted role not configured."), ephemeral=True
            )
            return

        muted_role = interaction.guild.get_role(muted_role_id)
        if muted_role and muted_role in user.roles:
            await user.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason}")

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="UNMUTE", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("Member Unmuted", f"{user.mention} unmuted. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /timeout ──────────────────────────────────────────────────────────

    @app_commands.command(name="timeout", description="Timeout a member.")
    @app_commands.describe(
        user="Member to timeout",
        duration="Duration e.g. 10m, 2h (max 28d)",
        reason="Reason",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def timeout(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str = "10m",
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "moderate_members"):
            return
        if not await gate_hierarchy(interaction, user):
            return

        td = _parse_duration(duration)
        if td is None:
            await interaction.response.send_message(
                embed=embeds.error("Invalid Duration", "Use `10m`, `2h`, `1d` etc."),
                ephemeral=True,
            )
            return
        if td.total_seconds() > 28 * 86400:
            await interaction.response.send_message(
                embed=embeds.error("Too Long", "Discord timeout max is 28 days."),
                ephemeral=True,
            )
            return

        try:
            until = discord.utils.utcnow() + td
            await user.timeout(until, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I couldn't timeout that user."), ephemeral=True
            )
            return

        expires_at = datetime.now(timezone.utc) + td
        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="TIMEOUT", reason=reason,
            expires_at=expires_at,
            extra_fields=[("Duration", duration, True)],
        )
        await _dm_user(user, embeds.user_dm(
            guild_name=interaction.guild.name,
            action="Timeout",
            reason=reason,
            case_id=case_id,
            extra=f"**Duration:** {duration}",
        ))
        await interaction.response.send_message(
            embed=embeds.success("Timeout Applied", f"{user.mention} timed out for {duration}. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /untimeout ────────────────────────────────────────────────────────

    @app_commands.command(name="untimeout", description="Remove a timeout from a member.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def untimeout(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "moderate_members"):
            return
        try:
            await user.timeout(None, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "Could not remove timeout."), ephemeral=True
            )
            return
        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="UNTIMEOUT", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("Timeout Removed", f"{user.mention}'s timeout removed. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /kick ─────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "kick_members"):
            return
        if not await gate_hierarchy(interaction, user):
            return

        await _dm_user(user, embeds.user_dm(
            guild_name=interaction.guild.name,
            action="Kick",
            reason=reason,
        ))
        try:
            await interaction.guild.kick(user, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I couldn't kick that user."), ephemeral=True
            )
            return

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="KICK", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("Member Kicked", f"{user} was kicked. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /ban ──────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Ban a user from the server.")
    @app_commands.describe(
        user="Member to ban",
        reason="Reason",
        delete_days="Days of messages to delete (0-7)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
        delete_days: int = 0,
    ) -> None:
        if not await gate_permission(interaction, "ban_members"):
            return
        if not await gate_hierarchy(interaction, user):
            return

        delete_days = max(0, min(7, delete_days))
        await _dm_user(user, embeds.user_dm(
            guild_name=interaction.guild.name,
            action="Ban",
            reason=reason,
        ))
        try:
            await interaction.guild.ban(
                user,
                reason=f"Banned by {interaction.user}: {reason}",
                delete_message_days=delete_days,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I couldn't ban that user."), ephemeral=True
            )
            return

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="BAN", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("Member Banned", f"{user} was banned. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /unban ────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="User ID to unban", reason="Reason")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "ban_members"):
            return
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error("Invalid ID", "Provide a valid numeric user ID."), ephemeral=True
            )
            return
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=reason)
        except discord.NotFound:
            await interaction.response.send_message(
                embed=embeds.error("Not Found", "That user is not banned or does not exist."),
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I couldn't unban that user."), ephemeral=True
            )
            return

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="UNBAN", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("User Unbanned", f"{user} was unbanned. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /softban ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="softban",
        description="Ban then immediately unban a member to delete their messages.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def softban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "ban_members"):
            return
        if not await gate_hierarchy(interaction, user):
            return

        await _dm_user(user, embeds.user_dm(
            guild_name=interaction.guild.name, action="Softban", reason=reason
        ))
        try:
            await interaction.guild.ban(user, reason=reason, delete_message_days=7)
            await interaction.guild.unban(user, reason="Softban — auto-unban")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I couldn't softban that user."), ephemeral=True
            )
            return

        case_id = await _create_and_log(
            self.bot, interaction.guild,
            user=user, moderator=interaction.user,
            action="SOFTBAN", reason=reason,
        )
        await interaction.response.send_message(
            embed=embeds.success("Member Softbanned", f"{user} softbanned. Case #{case_id}"),
            ephemeral=True,
        )

    # ── /massban ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="massban",
        description="Ban multiple users by comma-separated IDs.",
    )
    @app_commands.describe(user_ids="Comma-separated user IDs", reason="Reason")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def massban(
        self,
        interaction: discord.Interaction,
        user_ids: str,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "ban_members"):
            return

        await interaction.response.defer(ephemeral=True)
        ids = [s.strip() for s in user_ids.split(",") if s.strip()]
        success_list, failed_list = [], []

        for raw_id in ids:
            try:
                uid = int(raw_id)
                user = await self.bot.fetch_user(uid)
                await interaction.guild.ban(user, reason=f"Massbanned by {interaction.user}: {reason}")
                await _create_and_log(
                    self.bot, interaction.guild,
                    user=user, moderator=interaction.user,
                    action="MASSBAN", reason=reason,
                )
                success_list.append(str(uid))
            except Exception as exc:
                log.warning("massban %s failed: %s", raw_id, exc)
                failed_list.append(raw_id)

        desc = f"**Banned ({len(success_list)}):** {', '.join(success_list) or 'none'}\n"
        if failed_list:
            desc += f"**Failed ({len(failed_list)}):** {', '.join(failed_list)}"
        await interaction.followup.send(embed=embeds.success("Mass Ban Complete", desc), ephemeral=True)

    # ── /masskick ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="masskick",
        description="Kick multiple members by comma-separated IDs.",
    )
    @app_commands.describe(user_ids="Comma-separated user IDs", reason="Reason")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def masskick(
        self,
        interaction: discord.Interaction,
        user_ids: str,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "kick_members"):
            return

        await interaction.response.defer(ephemeral=True)
        ids = [s.strip() for s in user_ids.split(",") if s.strip()]
        success_list, failed_list = [], []

        for raw_id in ids:
            try:
                uid = int(raw_id)
                member = interaction.guild.get_member(uid)
                if member is None:
                    failed_list.append(raw_id)
                    continue
                await interaction.guild.kick(member, reason=reason)
                await _create_and_log(
                    self.bot, interaction.guild,
                    user=member, moderator=interaction.user,
                    action="MASSKICK", reason=reason,
                )
                success_list.append(str(uid))
            except Exception as exc:
                log.warning("masskick %s failed: %s", raw_id, exc)
                failed_list.append(raw_id)

        desc = f"**Kicked ({len(success_list)}):** {', '.join(success_list) or 'none'}\n"
        if failed_list:
            desc += f"**Failed ({len(failed_list)}):** {', '.join(failed_list)}"
        await interaction.followup.send(embed=embeds.success("Mass Kick Complete", desc), ephemeral=True)

    # ── /clear ────────────────────────────────────────────────────────────

    @app_commands.command(name="clear", description="Bulk-delete messages in this channel.")
    @app_commands.describe(amount="Number of messages (1–100)", user="Only delete messages from this user")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: int,
        user: Optional[discord.Member] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_messages"):
            return

        amount = max(1, min(100, amount))
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(embed=embeds.error("Invalid Channel", "Use this in a text channel."), ephemeral=True)
            return

        def check(m: discord.Message) -> bool:
            return (user is None) or (m.author.id == user.id)

        try:
            deleted = await channel.purge(limit=amount, check=check)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=embeds.error("Failed", "I can't delete messages here."), ephemeral=True
            )
            return

        log_embed = discord.Embed(
            title="🧹 Messages Cleared",
            color=0x3498DB,
            description=(
                f"**{len(deleted)}** messages deleted in {channel.mention}\n"
                f"**By:** {interaction.user.mention}\n"
                + (f"**Filtered to:** {user.mention}" if user else "")
            ),
        )
        log_embed.timestamp = datetime.now(timezone.utc)
        await _log_action(self.bot, interaction.guild, log_embed)
        await interaction.followup.send(
            embed=embeds.success("Cleared", f"Deleted **{len(deleted)}** messages."), ephemeral=True
        )

    # ── /slowmode ─────────────────────────────────────────────────────────

    @app_commands.command(name="slowmode", description="Set slowmode on a channel.")
    @app_commands.describe(seconds="Slowmode in seconds (0 to disable)", channel="Target channel (default: current)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: int,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Invalid Channel", "Target must be a text channel."), ephemeral=True
            )
            return
        seconds = max(0, min(21600, seconds))
        try:
            await target.edit(slowmode_delay=seconds)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't edit that channel."), ephemeral=True
            )
            return
        msg = f"Slowmode {'disabled' if seconds == 0 else f'set to {seconds}s'} in {target.mention}"
        await interaction.response.send_message(embed=embeds.success("Slowmode Updated", msg), ephemeral=True)

    # ── /lock ─────────────────────────────────────────────────────────────

    @app_commands.command(name="lock", description="Lock a channel (prevent @everyone from sending).")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def lock(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Invalid Channel", "Target must be a text channel."), ephemeral=True
            )
            return
        everyone = interaction.guild.default_role
        try:
            await target.set_permissions(everyone, send_messages=False, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't edit that channel."), ephemeral=True
            )
            return
        await target.send(embed=embeds.warning("Channel Locked", f"This channel has been locked. Reason: {reason or 'N/A'}"))
        await interaction.response.send_message(
            embed=embeds.success("Channel Locked", f"{target.mention} is now locked."), ephemeral=True
        )

    # ── /unlock ───────────────────────────────────────────────────────────

    @app_commands.command(name="unlock", description="Unlock a channel.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unlock(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Invalid Channel", "Target must be a text channel."), ephemeral=True
            )
            return
        everyone = interaction.guild.default_role
        try:
            await target.set_permissions(everyone, send_messages=None, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't edit that channel."), ephemeral=True
            )
            return
        await target.send(embed=embeds.success("Channel Unlocked", "This channel has been unlocked."))
        await interaction.response.send_message(
            embed=embeds.success("Channel Unlocked", f"{target.mention} is now unlocked."), ephemeral=True
        )

    # ── /nick ─────────────────────────────────────────────────────────────

    @app_commands.command(name="nick", description="Change a member's nickname.")
    @app_commands.describe(user="Target member", nickname="New nickname (leave blank to reset)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def nick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        nickname: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_nicknames"):
            return
        if not await gate_hierarchy(interaction, user):
            return
        try:
            old = user.display_name
            await user.edit(nick=nickname)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't change that user's nickname."), ephemeral=True
            )
            return
        action = f"Nickname changed: `{old}` → `{nickname or 'reset'}`"
        await interaction.response.send_message(embed=embeds.success("Nickname Updated", action), ephemeral=True)

    # ── /role_add ─────────────────────────────────────────────────────────

    @app_commands.command(name="role_add", description="Add a role to a member.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def role_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role: discord.Role,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_roles"):
            return
        if not await gate_hierarchy(interaction, user):
            return
        if role in user.roles:
            await interaction.response.send_message(
                embed=embeds.warning("Already Has Role", f"{user.mention} already has {role.mention}."),
                ephemeral=True,
            )
            return
        try:
            await user.add_roles(role, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't assign that role."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Role Added", f"{role.mention} added to {user.mention}."), ephemeral=True
        )

    # ── /role_remove ──────────────────────────────────────────────────────

    @app_commands.command(name="role_remove", description="Remove a role from a member.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def role_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role: discord.Role,
        reason: Optional[str] = None,
    ) -> None:
        if not await gate_permission(interaction, "manage_roles"):
            return
        if not await gate_hierarchy(interaction, user):
            return
        if role not in user.roles:
            await interaction.response.send_message(
                embed=embeds.warning("Doesn't Have Role", f"{user.mention} doesn't have {role.mention}."),
                ephemeral=True,
            )
            return
        try:
            await user.remove_roles(role, reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "I can't remove that role."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Role Removed", f"{role.mention} removed from {user.mention}."), ephemeral=True
        )

    # ── /note_add ─────────────────────────────────────────────────────────

    @app_commands.command(name="note_add", description="Add a private staff note to a user.")
    @app_commands.describe(user="Target user", content="Note content")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def note_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        content: str,
    ) -> None:
        if not await gate_warn(interaction):
            return

        await db.ensure_user(user.id, interaction.guild.id)
        note_id = await db.add_note(
            user_id=user.id,
            moderator_id=interaction.user.id,
            content=content,
            guild_id=interaction.guild.id,
        )
        if note_id:
            log_embed = discord.Embed(
                title="📝 Staff Note Added",
                color=0x3498DB,
                description=content,
            )
            log_embed.add_field(name="User",      value=f"{user.mention} (`{user.id}`)", inline=True)
            log_embed.add_field(name="Moderator", value=f"{interaction.user.mention}",   inline=True)
            log_embed.add_field(name="Note ID",   value=f"#{note_id}",                  inline=True)
            log_embed.timestamp = datetime.now(timezone.utc)
            await _log_action(self.bot, interaction.guild, log_embed)
            await interaction.response.send_message(
                embed=embeds.success("Note Added", f"Note #{note_id} added to {user.mention}."),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "Could not save note. Check database connection."),
                ephemeral=True,
            )

    # ── /note_list ────────────────────────────────────────────────────────

    @app_commands.command(name="note_list", description="View all staff notes for a user.")
    @app_commands.describe(user="Target user")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def note_list(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if not await gate_warn(interaction):
            return

        notes = await db.get_notes(user.id, interaction.guild.id)
        if not notes:
            await interaction.response.send_message(
                embed=embeds.info("No Notes", f"No staff notes found for {user.mention}."),
                ephemeral=True,
            )
            return

        e = discord.Embed(title=f"📝 Staff Notes — {user}", color=0x3498DB)
        e.set_thumbnail(url=user.display_avatar.url)
        for note in notes[:10]:
            ts = note.get("timestamp", "")[:10]
            e.add_field(
                name=f"Note #{note['note_id']}  ({ts})",
                value=f"{note['content'][:200]}\n*— <@{note['moderator_id']}>*",
                inline=False,
            )
        e.set_footer(text=f"Showing {min(len(notes), 10)}/{len(notes)} notes  •  User ID: {user.id}")
        e.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /note_delete ──────────────────────────────────────────────────────

    @app_commands.command(name="note_delete", description="Delete a staff note by its ID.")
    @app_commands.describe(note_id="The note ID to delete")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def note_delete(
        self,
        interaction: discord.Interaction,
        note_id: int,
    ) -> None:
        if not await gate_warn(interaction):
            return

        ok = await db.delete_note(note_id)
        if ok:
            await interaction.response.send_message(
                embed=embeds.success("Note Deleted", f"Note #{note_id} has been deleted."),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error("Failed", f"Could not delete note #{note_id}."),
                ephemeral=True,
            )

    # ── Error handler ─────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        msg = "❌ Something went wrong. Please try again later."
        if isinstance(error, app_commands.MissingPermissions):
            msg = f"❌ You don't have permission to use this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "❌ I don't have the required permissions."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"❌ Command on cooldown. Retry in {error.retry_after:.1f}s."
        log.error("ModerationCog error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embeds.error("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=embeds.error("Error", msg), ephemeral=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# History Paginator View
# ---------------------------------------------------------------------------

class HistoryPaginator(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        user: discord.Member,
        guild_id: int,
        current_page: int,
        total_pages: int,
        cases: list[dict],
    ) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user = user
        self.guild_id = guild_id
        self.page = current_page
        self.total_pages = total_pages
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction) -> None:
        from config import HISTORY_PAGE_SIZE
        cases, total = await db.get_cases(self.user.id, self.guild_id, self.page, HISTORY_PAGE_SIZE)
        self.total_pages = max(1, -(-total // HISTORY_PAGE_SIZE))
        self._update_buttons()
        await interaction.response.edit_message(
            embed=embeds.case_list(self.user, cases, self.page, self.total_pages),
            view=self,
        )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
