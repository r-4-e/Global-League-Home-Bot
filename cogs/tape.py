"""
cogs/tape.py — Tape & Recover System for Elura.

Commands:
  gl.tape <@user>     — Strip all roles and store them in Supabase
                        (usable by anyone with Administrator permission)
  gl.recover <@user>  — Restore all stored roles back to the user

Rules:
  - Requires Administrator permission (or dev ID)
  - Cannot tape/recover someone with a higher or equal top role
  - Dev (858409278473240597) bypasses all hierarchy checks
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from database import db

log = logging.getLogger(__name__)

DEV_ID    = 858409278473240597
TAPE_RULE = "tape_roles"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_all_taped(guild_id: int) -> dict:
    """Returns {user_id_str: [role_id, ...], ...}"""
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == TAPE_RULE:
            return r.get("config") or {}
    return {}


async def _save_taped(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(TAPE_RULE, True, data, guild_id)


# ---------------------------------------------------------------------------
# Permission check
# ---------------------------------------------------------------------------

def has_admin():
    """Allow if invoker is the dev OR has Administrator permission."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == DEV_ID:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        await ctx.send("You need Administrator permission to use this command.")
        return False
    return commands.check(predicate)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class TapeCog(commands.Cog, name="Tape"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="rape")
    @has_admin()
    async def Tape(self, ctx: commands.Context, member: discord.Member) -> None:
        """Strip all roles from a user and store them in Supabase."""

        # Hierarchy guard — dev bypasses, everyone else is checked
        if ctx.author.id != DEV_ID:
            if member.id == ctx.author.id:
                await ctx.send("You can't rape yourself.")
                return
            if member.top_role >= ctx.author.top_role:
                await ctx.send("You can't rape someone who is higher or equal to you.")
                return

        # Collect every role except @everyone and roles above the bot
        roles_to_remove = [
            r for r in member.roles
            if r != ctx.guild.default_role and r < ctx.guild.me.top_role
        ]

        if not roles_to_remove:
            await ctx.send(f"{member.mention} has no roles to rape.")
            return

        # Store role IDs in Supabase
        all_taped = await _get_all_taped(ctx.guild.id)
        all_taped[str(member.id)] = [r.id for r in roles_to_remove]
        await _save_taped(ctx.guild.id, all_taped)

        # Strip the roles
        try:
            await member.remove_roles(*roles_to_remove, reason=f"Taped by {ctx.author}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to remove those roles.")
            return
        except discord.HTTPException as e:
            await ctx.send(f"Something went wrong: {e}")
            return

        await ctx.send(f"{member.mention} has been Raped <3")

    @commands.command(name="recover")
    @has_admin()
    async def recover(self, ctx: commands.Context, member: discord.Member) -> None:
        """Restore all stored roles back to a raped user."""

        # Hierarchy guard — dev bypasses, everyone else is checked
        if ctx.author.id != DEV_ID:
            if member.id == ctx.author.id:
                await ctx.send("You can't recover yourself.")
                return
            if member.top_role >= ctx.author.top_role:
                await ctx.send("You can't recover someone who is higher or equal to you.")
                return

        all_taped = await _get_all_taped(ctx.guild.id)
        stored_ids = all_taped.get(str(member.id))

        if not stored_ids:
            await ctx.send(f"{member.mention} has no stored roles to recover.")
            return

        # Resolve role objects — skip deleted or unmanageable roles
        roles_to_give = [
            ctx.guild.get_role(rid)
            for rid in stored_ids
            if ctx.guild.get_role(rid) is not None
            and ctx.guild.get_role(rid) < ctx.guild.me.top_role
        ]

        if not roles_to_give:
            await ctx.send("None of the stored roles exist anymore.")
            return

        try:
            await member.add_roles(*roles_to_give, reason=f"Recovered by {ctx.author}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to give those roles.")
            return
        except discord.HTTPException as e:
            await ctx.send(f"Something went wrong: {e}")
            return

        # Clean up from Supabase
        del all_taped[str(member.id)]
        await _save_taped(ctx.guild.id, all_taped)

        await ctx.send(f"Recovered {member.mention} roles <3")

    # ── Errors ────────────────────────────────────────────────────────────

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CheckFailure):
            return  # message already sent inside the check
        if isinstance(error, commands.MemberNotFound):
            await ctx.send("Couldn't find that user.")
            return
        log.error("TapeCog error: %s", error)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TapeCog(bot))
