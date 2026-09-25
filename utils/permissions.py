"""
utils/permissions.py — Permission middleware for Global League Bot.

GL Staff Hierarchy (lowest → highest):

  ── STAFF (LR+) ──
  Tier 1 — Trial Staff         1515935527101272114  View staff channels, read history, respond to tickets
  Tier 2 — Staff               1515936007902593084  + Attach files, embed links

  ── MODERATION (MR+) ──
  Tier 3 — Trial Moderator     1515937742293438535  + Change nickname, add reactions, timeout ≤1h
  Tier 4 — Moderator           1515938178182287380  + Manage messages

  ── ADMINISTRATION (HR+) ──
  Tier 5 — Trial Administrator 1515942111193862264  + Voice mute, deafen, move
  Tier 6 — Administrator       1515942294245871708  + Extended timeout ≤1w, manage threads, kick

  ── LEADERSHIP (LEAD) ──
  Tier 7 — Head Moderator      1515943605246890036  + Ban, audit logs, manage channels, slowmode
  Tier 8 — Head Administrator  1515943852387733615  + Mention everyone/here, manage events, nicknames
  Tier 9 — Head Staff          1530927074838052864  + Manage webhooks & integrations

  ── SHR+ ──
  Tier 10 — Staff Manager      1515945187703128136  + Manage roles & server, full oversight

Bot owner (GL server owner): 1485610704441577552 — bypasses everything
Legacy BOT_OWNER_ID kept for backward compat: 858409278473240597
"""

from __future__ import annotations

import discord
from discord.ext import commands

# ── Owner IDs ─────────────────────────────────────────────────────────────────
GL_OWNER_ID  = 1485610704441577552
BOT_OWNER_ID = 858409278473240597

OWNER_IDS = {GL_OWNER_ID, BOT_OWNER_ID}

# ── Hierarchy role IDs (ordered lowest → highest) ────────────────────────────
TIER_1  = 1515935527101272114   # Trial Staff
TIER_2  = 1515936007902593084   # Staff
TIER_3  = 1515937742293438535   # Trial Moderator
TIER_4  = 1515938178182287380   # Moderator
TIER_5  = 1515942111193862264   # Trial Administrator
TIER_6  = 1515942294245871708   # Administrator
TIER_7  = 1515943605246890036   # Head Moderator
TIER_8  = 1515943852387733615   # Head Administrator
TIER_9  = 1530927074838052864   # Head Staff
TIER_10 = 1515945187703128136   # Staff Manager

HIERARCHY: list[int] = [
    TIER_1, TIER_2, TIER_3, TIER_4, TIER_5,
    TIER_6, TIER_7, TIER_8, TIER_9, TIER_10,
]

TIER_PERMISSIONS: dict[int, set[str]] = {
    TIER_1:  {"view_history", "read_tickets"},
    TIER_2:  {"attach_files", "embed_links"},
    TIER_3:  {"change_nickname", "add_reactions", "timeout_minor"},
    TIER_4:  {"manage_messages"},
    TIER_5:  {"voice_mute", "voice_deafen", "voice_move"},
    TIER_6:  {"timeout_extended", "manage_threads", "kick_members"},
    TIER_7:  {"ban_members", "view_audit_log", "manage_channels", "slowmode"},
    TIER_8:  {"mention_everyone", "manage_events", "manage_nicknames"},
    TIER_9:  {"manage_webhooks"},
    TIER_10: {"manage_roles", "manage_guild"},
}

WARN_ROLE_ID = TIER_3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _member_tier(member: discord.Member) -> int:
    role_ids = {r.id for r in member.roles}
    tier = 0
    for i, role_id in enumerate(HIERARCHY, start=1):
        if role_id in role_ids:
            tier = i
    return tier


def _has_staff_perm(member: discord.Member, perm: str) -> bool:
    if _is_owner(member.id):
        return True
    member_tier = _member_tier(member)
    if member_tier == 0:
        return False
    granted: set[str] = set()
    for i, role_id in enumerate(HIERARCHY, start=1):
        if i > member_tier:
            break
        granted |= TIER_PERMISSIONS.get(role_id, set())
    return perm in granted


def get_tier_name(tier: int) -> str:
    names = {
        0:  "No Staff Role",
        1:  "Trial Staff",
        2:  "Staff",
        3:  "Trial Moderator",
        4:  "Moderator",
        5:  "Trial Administrator",
        6:  "Administrator",
        7:  "Head Moderator",
        8:  "Head Administrator",
        9:  "Head Staff",
        10: "Staff Manager",
    }
    return names.get(tier, "Unknown")


def get_tier_section(tier: int) -> str:
    if tier <= 2:
        return "LR+ | Staff"
    if tier <= 4:
        return "MR+ | Moderation"
    if tier <= 6:
        return "HR+ | Administration"
    if tier <= 9:
        return "LEAD | Leadership"
    return "SHR+ | Staff Manager"


# ── Gate functions ────────────────────────────────────────────────────────────

async def gate_tier(ctx: commands.Context, min_tier: int) -> bool:
    if _is_owner(ctx.author.id):
        return True
    if not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ This command can only be used inside the server.")
        return False
    tier = _member_tier(ctx.author)
    if tier < min_tier:
        required_name = get_tier_name(min_tier)
        section = get_tier_section(min_tier)
        await ctx.send(
            f"❌ You need at least **{required_name}** ({section}) to use this command."
        )
        return False
    return True


async def gate_warn(ctx: commands.Context) -> bool:
    """Warn commands require Tier 3 (Trial Moderator) or higher."""
    return await gate_tier(ctx, 3)


def max_auto_punishment(moderator: discord.Member) -> str:
    """
    Returns the maximum auto-punishment a warn threshold can trigger,
    capped at the issuing moderator's own permission level.

    This prevents lower staff from abusing warn thresholds to trigger
    bans or kicks they could not issue manually.

    Tier 3-4 (MR+)  -> max: timeout
    Tier 5-6 (HR+)  -> max: kick
    Tier 7+  (LEAD) -> max: ban
    Owner           -> no cap
    """
    if _is_owner(moderator.id):
        return "ban"
    tier = _member_tier(moderator)
    if tier >= 7:
        return "ban"
    if tier >= 6:
        return "kick"
    if tier >= 3:
        return "timeout"
    return "warn"


def can_auto_punish(moderator: discord.Member, action: str) -> tuple[bool, str]:
    """
    Synchronous check — returns (allowed, reason).
    Call this inside warn_threshold before applying any auto-punishment.

    action: "warn" | "timeout" | "kick" | "ban"
    """
    if _is_owner(moderator.id):
        return True, ""

    order   = ["warn", "timeout", "kick", "ban"]
    allowed = max_auto_punishment(moderator)

    if order.index(action) > order.index(allowed):
        tier = _member_tier(moderator)
        return False, (
            f"Auto-punishment capped: **{get_tier_name(tier)}** can only "
            f"auto-escalate up to **{allowed}**, not **{action}**. "
            f"Contact a higher-ranked staff member to proceed."
        )
    return True, ""


async def gate_permission(ctx: commands.Context, perm: str) -> bool:
    if _is_owner(ctx.author.id):
        return True

    if not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ This command can only be used inside the server.")
        return False

    if not _has_staff_perm(ctx.author, perm):
        tier = _member_tier(ctx.author)
        required_tier = next(
            (i for i, rid in enumerate(HIERARCHY, start=1)
             if perm in TIER_PERMISSIONS.get(rid, set())),
            None,
        )
        if required_tier:
            section = get_tier_section(required_tier)
            await ctx.send(
                f"❌ You need **{get_tier_name(required_tier)}** ({section}) "
                f"to use this command. You are currently **{get_tier_name(tier)}**."
            )
        else:
            await ctx.send("❌ You don't have permission to use this command.")
        return False

    bot_member = ctx.guild.me
    channel = ctx.channel
    if isinstance(channel, discord.abc.GuildChannel):
        bot_perms = channel.permissions_for(bot_member)
    else:
        bot_perms = bot_member.guild_permissions

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
        if target.top_role >= guild.me.top_role:
            await ctx.send("❌ I can't action this member — they're above my top role.")
            return False
        return True

    invoker_tier = _member_tier(invoker)
    target_tier  = _member_tier(target)

    if invoker_tier > 0 and target_tier >= invoker_tier:
        await ctx.send(
            f"❌ You cannot action **{target.display_name}** — "
            f"they hold an equal or higher rank (**{get_tier_name(target_tier)}**)."
        )
        return False

    if target.top_role >= guild.me.top_role:
        await ctx.send("❌ I can't action this member — their role is above mine.")
        return False

    if invoker_tier == 0 and target.top_role >= invoker.top_role:
        await ctx.send("❌ You cannot action a member with an equal or higher role.")
        return False

    return True


async def gate_timeout_duration(ctx: commands.Context, seconds: int) -> bool:
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
                "❌ Your rank (**Trial Moderator**, Tier 3) can only timeout up to **1 hour**. "
                "You need **Administrator** (Tier 6) for longer timeouts."
            )
            return False
        return True
    await ctx.send("❌ You need at least **Trial Moderator** (MR+) to issue timeouts.")
    return False


# ── Legacy shims ──────────────────────────────────────────────────────────────

def has_warn_role(ctx: commands.Context) -> bool:
    if _is_owner(ctx.author.id):
        return True
    if not isinstance(ctx.author, discord.Member):
        return False
    return _member_tier(ctx.author) >= 3


def check_invoker_permission(ctx: commands.Context, perm: str) -> tuple[bool, str]:
    if _is_owner(ctx.author.id):
        return True, ""
    member = ctx.author
    if not isinstance(member, discord.Member):
        return False, "❌ Must be used in a server."
    if _has_staff_perm(member, perm):
        return True, ""
    return False, "❌ You don't have permission to use this command."


def _is_staff_member(member: discord.Member) -> bool:
    """Returns True if member has any GL staff tier (Tier 1+) or is admin."""
    if member.guild_permissions.administrator:
        return True
    return _member_tier(member) >= 1
