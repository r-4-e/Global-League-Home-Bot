"""
utils/permissions.py — Permission middleware for Global League Bot.

GL Staff Hierarchy (lowest → highest):
  Tier 1 — Trial Moderator      1515935527101272114  read history, tickets, staff channels
  Tier 2 — Junior Moderator     1515936007902593084  + attach files & embed links
  Tier 3 — Moderator            1515937742293438535  + change nickname, add reactions, timeout (≤1h)
  Tier 4 — Senior Moderator     1515938178182287380  + manage messages
  Tier 5 — Chat Manager         1515942111193862264  + voice moderation
  Tier 6 — Staff Manager        1515942294245871708  + extended timeout (≤1w), manage threads, kick
  Tier 7 — Head Moderator       1515943605246890036  + ban, audit logs, manage channels, slowmode
  Tier 8 — Community Manager    1515943852387733615  + mention @everyone/@here, manage events, nicknames
  Tier 9 — Operations Manager   1530927074838052864  + manage webhooks & integrations
  Tier 10 — Senior Staff        1515945187703128136  + manage roles & server

Bot owner (GL server owner): 1485610704441577552 — bypasses everything
Legacy BOT_OWNER_ID kept for backward compat: 858409278473240597
"""

from __future__ import annotations

import discord
from discord.ext import commands

# ── Owner IDs ─────────────────────────────────────────────────────────────────
GL_OWNER_ID   = 1485610704441577552   # you — bypasses all checks
BOT_OWNER_ID  = 858409278473240597    # legacy — kept so existing code doesn't break

OWNER_IDS = {GL_OWNER_ID, BOT_OWNER_ID}

# ── Hierarchy role IDs (ordered lowest → highest) ────────────────────────────
TIER_1  = 1515935527101272114   # Trial Moderator
TIER_2  = 1515936007902593084   # Junior Moderator
TIER_3  = 1515937742293438535   # Moderator
TIER_4  = 1515938178182287380   # Senior Moderator
TIER_5  = 1515942111193862264   # Chat Manager
TIER_6  = 1515942294245871708   # Staff Manager
TIER_7  = 1515943605246890036   # Head Moderator
TIER_8  = 1515943852387733615   # Community Manager
TIER_9  = 1530927074838052864   # Operations Manager
TIER_10 = 1515945187703128136   # Senior Staff

# Ordered list — index 0 = lowest
HIERARCHY: list[int] = [
    TIER_1, TIER_2, TIER_3, TIER_4, TIER_5,
    TIER_6, TIER_7, TIER_8, TIER_9, TIER_10,
]

# What each tier unlocks for mod commands
TIER_PERMISSIONS: dict[int, set[str]] = {
    TIER_1:  {"view_history", "read_tickets"},
    TIER_2:  {"attach_files", "embed_links"},
    TIER_3:  {"change_nickname", "add_reactions", "timeout_minor"},   # timeout ≤ 1h
    TIER_4:  {"manage_messages"},
    TIER_5:  {"voice_mute", "voice_deafen", "voice_move"},
    TIER_6:  {"timeout_extended", "manage_threads", "kick_members"},  # timeout ≤ 1w
    TIER_7:  {"ban_members", "view_audit_log", "manage_channels", "slowmode"},
    TIER_8:  {"mention_everyone", "manage_events", "manage_nicknames"},
    TIER_9:  {"manage_webhooks"},
    TIER_10: {"manage_roles", "manage_guild"},
}

# Legacy WARN_ROLE_ID shim — tier 3+ can warn
WARN_ROLE_ID = TIER_3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _member_tier(member: discord.Member) -> int:
    """
    Returns the highest staff tier the member holds (1–10),
    or 0 if they have no staff role.
    """
    role_ids = {r.id for r in member.roles}
    tier = 0
    for i, role_id in enumerate(HIERARCHY, start=1):
        if role_id in role_ids:
            tier = i
    return tier


def _has_staff_perm(member: discord.Member, perm: str) -> bool:
    """
    Returns True if the member's tier grants the given GL permission,
    OR if their Discord guild permissions grant it (for bot's own checks).
    All tiers inherit perms from tiers below them.
    """
    if _is_owner(member.id):
        return True
    member_tier = _member_tier(member)
    if member_tier == 0:
        return False
    # Accumulate all perms up to and including the member's tier
    granted: set[str] = set()
    for i, role_id in enumerate(HIERARCHY, start=1):
        if i > member_tier:
            break
        granted |= TIER_PERMISSIONS.get(role_id, set())
    return perm in granted


def get_tier_name(tier: int) -> str:
    names = {
        0:  "No Staff Role",
        1:  "Trial Moderator",
        2:  "Junior Moderator",
        3:  "Moderator",
        4:  "Senior Moderator",
        5:  "Chat Manager",
        6:  "Staff Manager",
        7:  "Head Moderator",
        8:  "Community Manager",
        9:  "Operations Manager",
        10: "Senior Staff",
    }
    return names.get(tier, "Unknown")


# ── Gate functions (used in cogs) ────────────────────────────────────────────

async def gate_tier(ctx: commands.Context, min_tier: int) -> bool:
    """Pass if the invoker holds at least `min_tier`."""
    if _is_owner(ctx.author.id):
        return True
    if not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ This command can only be used inside the server.")
        return False
    tier = _member_tier(ctx.author)
    if tier < min_tier:
        required_name = get_tier_name(min_tier)
        await ctx.send(
            f"❌ You need at least **{required_name}** (Tier {min_tier}) to use this command."
        )
        return False
    return True


async def gate_warn(ctx: commands.Context) -> bool:
    """Warn commands require Tier 3 (Moderator) or higher."""
    return await gate_tier(ctx, 3)


async def gate_permission(ctx: commands.Context, perm: str) -> bool:
    """
    Check if the invoker has a specific GL staff permission.
    Also verifies the bot itself has the corresponding Discord permission.
    """
    if _is_owner(ctx.author.id):
        return True

    if not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ This command can only be used inside the server.")
        return False

    if not _has_staff_perm(ctx.author, perm):
        tier = _member_tier(ctx.author)
        # Find which tier grants this perm
        required_tier = next(
            (i for i, rid in enumerate(HIERARCHY, start=1)
             if perm in TIER_PERMISSIONS.get(rid, set())),
            None,
        )
        if required_tier:
            await ctx.send(
                f"❌ You need **{get_tier_name(required_tier)}** (Tier {required_tier}) "
                f"to use this command. You are currently Tier {tier} ({get_tier_name(tier)})."
            )
        else:
            await ctx.send("❌ You don't have permission to use this command.")
        return False

    # Check the bot also has the required Discord permission
    bot_member = ctx.guild.me
    channel    = ctx.channel
    if isinstance(channel, discord.abc.GuildChannel):
        bot_perms = channel.permissions_for(bot_member)
    else:
        bot_perms = bot_member.guild_permissions

    # Map GL perms → Discord perms for bot check
    discord_perm_map = {
        "ban_members":      "ban_members",
        "kick_members":     "kick_members",
        "manage_messages":  "manage_messages",
        "manage_channels":  "manage_channels",
        "manage_roles":     "manage_roles",
        "manage_guild":     "manage_guild",
        "manage_nicknames": "manage_nicknames",
        "manage_webhooks":  "manage_webhooks",
        "manage_threads":   "manage_threads",
        "view_audit_log":   "view_audit_log",
        "mention_everyone": "mention_everyone",
        "manage_events":    "manage_events",
        "timeout_minor":    "moderate_members",
        "timeout_extended": "moderate_members",
        "voice_mute":       "mute_members",
        "voice_deafen":     "deafen_members",
        "voice_move":       "move_members",
    }
    discord_perm = discord_perm_map.get(perm)
    if discord_perm and not getattr(bot_perms, discord_perm, True):
        await ctx.send("❌ I don't have the required Discord permission to perform this action.")
        return False

    return True


async def gate_hierarchy(ctx: commands.Context, target: discord.Member) -> bool:
    """
    Prevent staff from actioning members at the same tier or higher.
    Bot owner bypasses this — only limited by the bot's own top role.
    """
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

    if _is_owner(invoker.id):
        # Owner only limited by bot's own role
        if target.top_role >= guild.me.top_role:
            await ctx.send("❌ I can't action this member — they're above my top role.")
            return False
        return True

    # GL staff hierarchy check
    invoker_tier = _member_tier(invoker)
    target_tier  = _member_tier(target)

    if invoker_tier > 0 and target_tier >= invoker_tier:
        await ctx.send(
            f"❌ You cannot action **{target.display_name}** — "
            f"they hold an equal or higher staff rank ({get_tier_name(target_tier)})."
        )
        return False

    # Discord role hierarchy check (bot must be above target)
    if target.top_role >= guild.me.top_role:
        await ctx.send("❌ I can't action this member — their role is above mine.")
        return False

    # Standard role hierarchy for non-staff invokers
    if invoker_tier == 0 and target.top_role >= invoker.top_role:
        await ctx.send("❌ You cannot action a member with an equal or higher role.")
        return False

    return True


async def gate_timeout_duration(ctx: commands.Context, seconds: int) -> bool:
    """
    Tier 3 can timeout up to 1 hour.
    Tier 6+ can timeout up to 1 week.
    Owner unlimited.
    """
    if _is_owner(ctx.author.id):
        return True
    if not isinstance(ctx.author, discord.Member):
        return False
    tier = _member_tier(ctx.author)
    if tier >= 6:
        if seconds > 7 * 86400:
            await ctx.send("❌ Maximum timeout is 7 days.")
            return False
        return True
    if tier >= 3:
        if seconds > 3600:
            await ctx.send(
                "❌ Your rank (**Moderator**, Tier 3) can only timeout up to **1 hour**. "
                "You need **Staff Manager** (Tier 6) for longer timeouts."
            )
            return False
        return True
    await ctx.send("❌ You need at least **Moderator** (Tier 3) to issue timeouts.")
    return False


# ── Legacy shims (keeps old call sites working) ───────────────────────────────

def has_warn_role(ctx: commands.Context) -> bool:
    if _is_owner(ctx.author.id):
        return True
    if not isinstance(ctx.author, discord.Member):
        return False
    return _member_tier(ctx.author) >= 3


def check_invoker_permission(ctx: commands.Context, perm: str) -> tuple[bool, str]:
    """Synchronous check — returns (ok, error_message)."""
    if _is_owner(ctx.author.id):
        return True, ""
    member = ctx.author
    if not isinstance(member, discord.Member):
        return False, "❌ Must be used in a server."
    if _has_staff_perm(member, perm):
        return True, ""
    return False, f"❌ You don't have permission to use this command."
