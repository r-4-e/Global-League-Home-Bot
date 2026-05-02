"""
utils/permissions.py — Permission middleware for Global League Bot (prefix commands).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from config import WARN_ROLE_ID

# Bot owner — bypasses all permission and hierarchy checks
BOT_OWNER_ID = 858409278473240597


# ---------------------------------------------------------------------------
# Warn role check
# ---------------------------------------------------------------------------

def has_warn_role(ctx: commands.Context) -> bool:
    if ctx.author.id == BOT_OWNER_ID:
        return True
    member = ctx.author
    if not isinstance(member, discord.Member):
        return False
    return WARN_ROLE_ID in {r.id for r in member.roles}


async def gate_warn(ctx: commands.Context) -> bool:
    if ctx.author.id == BOT_OWNER_ID:
        return True
    if not has_warn_role(ctx):
        await ctx.send("❌ You are not allowed to use warning commands.")
        return False
    return True


# ---------------------------------------------------------------------------
# Discord permission checks
# ---------------------------------------------------------------------------

_PERM_LABELS: dict[str, str] = {
    "ban_members":      "Ban Members",
    "kick_members":     "Kick Members",
    "moderate_members": "Timeout Members",
    "mute_members":     "Mute Members",
    "manage_roles":     "Manage Roles",
    "manage_messages":  "Manage Messages",
    "manage_channels":  "Manage Channels",
    "manage_nicknames": "Manage Nicknames",
    "administrator":    "Administrator",
}


async def gate_permission(ctx: commands.Context, perm: str) -> bool:
    # Bot owner bypasses all permission checks
    if ctx.author.id == BOT_OWNER_ID:
        return True

    member = ctx.author
    if not isinstance(member, discord.Member):
        await ctx.send("❌ This command can only be used inside the server.")
        return False

    if not getattr(member.guild_permissions, perm, False):
        label = _PERM_LABELS.get(perm, perm.replace("_", " ").title())
        await ctx.send(f'❌ You need **"{label}"** permission to use this command.')
        return False

    # Check bot permission
    bot_member = ctx.guild.me
    channel    = ctx.channel
    if isinstance(channel, discord.abc.GuildChannel):
        bot_perms = channel.permissions_for(bot_member)
    else:
        bot_perms = bot_member.guild_permissions

    if not getattr(bot_perms, perm, False):
        await ctx.send("❌ I don't have permission to perform this action.")
        return False

    return True


# ---------------------------------------------------------------------------
# Role hierarchy protection
# ---------------------------------------------------------------------------

async def gate_hierarchy(ctx: commands.Context, target: discord.Member) -> bool:
    invoker = ctx.author
    guild   = ctx.guild

    if not isinstance(invoker, discord.Member) or guild is None:
        await ctx.send("❌ Hierarchy check failed.")
        return False

    if invoker.id == target.id:
        await ctx.send("❌ You cannot perform this action on yourself.")
        return False

    if target.id == guild.owner_id:
        await ctx.send("❌ You cannot perform this action on the server owner.")
        return False

    # Bot owner bypasses role hierarchy — only limited by bot's own top role
    if invoker.id == BOT_OWNER_ID:
        bot_member = guild.me
        if target.top_role >= bot_member.top_role:
            await ctx.send("❌ I don't have permission to perform this action (bot role hierarchy).")
            return False
        return True

    if target.top_role >= invoker.top_role:
        await ctx.send("❌ You cannot perform this action on a member with an equal or higher role.")
        return False

    bot_member = guild.me
    if target.top_role >= bot_member.top_role:
        await ctx.send("❌ I don't have permission to perform this action (role hierarchy).")
        return False

    return True


def check_invoker_permission(ctx: commands.Context, perm: str) -> tuple[bool, str]:
    """Synchronous check — returns (ok, error_message)."""
    # Bot owner always passes
    if ctx.author.id == BOT_OWNER_ID:
        return True, ""
    member = ctx.author
    if not isinstance(member, discord.Member):
        return False, "❌ Must be used in a server."
    if getattr(member.guild_permissions, perm, False):
        return True, ""
    label = _PERM_LABELS.get(perm, perm.replace("_", " ").title())
    return False, f'❌ You need **"{label}"** permission.'
