"""
utils/permissions.py — Permission middleware for Elura.

Every slash command should call the appropriate check from this module
before performing any action.  All checks return (allowed: bool, reason: str).
"""

from __future__ import annotations

import discord
from config import WARN_ROLE_ID


# ---------------------------------------------------------------------------
# Warn-system gating
# ---------------------------------------------------------------------------

def has_warn_role(interaction: discord.Interaction) -> tuple[bool, str]:
    """
    Returns (True, "") if the invoker holds the designated warn-role.
    Returns (False, error_message) otherwise.
    """
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False, "❌ This command can only be used inside the server."
    role_ids = {r.id for r in member.roles}
    if WARN_ROLE_ID in role_ids:
        return True, ""
    return False, "❌ You are not allowed to use warning commands."


# ---------------------------------------------------------------------------
# Standard Discord permission checks
# ---------------------------------------------------------------------------

_PERM_LABELS: dict[str, str] = {
    "ban_members":      "Ban Members",
    "kick_members":     "Kick Members",
    "moderate_members": "Timeout Members",   # Discord API name; displayed as spec requires
    "mute_members":     "Mute Members",
    "manage_roles":     "Manage Roles",
    "manage_messages":  "Manage Messages",
    "manage_channels":  "Manage Channels",
    "manage_nicknames": "Manage Nicknames",
}


def check_invoker_permission(
    interaction: discord.Interaction, perm: str
) -> tuple[bool, str]:
    """
    Check that the command invoker holds a given Discord permission.

    :param perm: snake_case attribute name on discord.Permissions, e.g. "ban_members"
    """
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False, "❌ This command can only be used inside the server."
    perms: discord.Permissions = member.guild_permissions
    if getattr(perms, perm, False):
        return True, ""
    label = _PERM_LABELS.get(perm, perm.replace("_", " ").title())
    return False, f'❌ You need **"{label}"** permission to use this command.'


def check_bot_permission(
    interaction: discord.Interaction, perm: str
) -> tuple[bool, str]:
    """
    Check that the bot itself holds a given permission in the current channel.
    """
    guild = interaction.guild
    if guild is None:
        return False, "❌ Guild not found."
    bot_member = guild.me
    channel = interaction.channel
    if channel is None or not isinstance(channel, discord.abc.GuildChannel):
        bot_perms = bot_member.guild_permissions
    else:
        bot_perms = channel.permissions_for(bot_member)
    if getattr(bot_perms, perm, False):
        return True, ""
    return False, "❌ I don't have permission to perform this action."


# ---------------------------------------------------------------------------
# Role hierarchy protection
# ---------------------------------------------------------------------------

def check_hierarchy(
    interaction: discord.Interaction,
    target: discord.Member,
) -> tuple[bool, str]:
    """
    Ensure the invoker can act on `target` according to role hierarchy rules.

    Rules
    -----
    - Cannot act on yourself
    - Cannot act on the guild owner
    - Cannot act on a member with equal or higher top role
      (guild owner is always exempt — their actions are always allowed)
    """
    invoker = interaction.user
    guild   = interaction.guild

    if not isinstance(invoker, discord.Member) or guild is None:
        return False, "❌ Hierarchy check failed (not in a guild)."

    # Self-action
    if invoker.id == target.id:
        return False, "❌ You cannot perform this action on yourself."

    # Target is guild owner
    if target.id == guild.owner_id:
        return False, "❌ You cannot perform this action on the server owner."

    # Invoker is guild owner — always allowed
    if invoker.id == guild.owner_id:
        return True, ""

    # Role hierarchy
    if target.top_role >= invoker.top_role:
        return False, (
            "❌ You cannot perform this action on a member with an equal or higher role."
        )

    return True, ""


def check_bot_hierarchy(
    interaction: discord.Interaction,
    target: discord.Member,
) -> tuple[bool, str]:
    """
    Ensure the BOT can act on `target` by hierarchy.
    """
    guild = interaction.guild
    if guild is None:
        return False, "❌ Guild not found."
    bot_member = guild.me
    if target.top_role >= bot_member.top_role:
        return False, "❌ I don't have permission to perform this action (role hierarchy)."
    return True, ""


# ---------------------------------------------------------------------------
# Combined gate helpers
# ---------------------------------------------------------------------------

async def gate_warn(interaction: discord.Interaction) -> bool:
    """
    Block execution and send an ephemeral error if the invoker may NOT use warn commands.
    Returns True when execution should CONTINUE, False when it should STOP.
    """
    ok, msg = has_warn_role(interaction)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
    return ok


async def gate_permission(
    interaction: discord.Interaction, perm: str
) -> bool:
    """Check invoker + bot permission.  Returns True if both pass."""
    ok, msg = check_invoker_permission(interaction, perm)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
        return False
    ok, msg = check_bot_permission(interaction, perm)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
        return False
    return True


async def gate_hierarchy(
    interaction: discord.Interaction,
    target: discord.Member,
) -> bool:
    """Check invoker hierarchy AND bot hierarchy.  Returns True if both pass."""
    ok, msg = check_hierarchy(interaction, target)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
        return False
    ok, msg = check_bot_hierarchy(interaction, target)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
        return False
    return True
