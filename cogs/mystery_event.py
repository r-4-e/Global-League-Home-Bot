"""
cogs/mystery_event.py — Mystery Event System for Elura.

Commands:
  Host only: gl.mystery_set <word>      — Set the secret word
             gl.mystery_clue <text>     — Add a daily clue
             gl.mystery_status          — View qualifiers + clues
             gl.mystery_qualify <user>  — Manually qualify a user
             gl.mystery_reset           — Reset the entire event
             gl.mystery_spin            — Spin the wheel & announce winner

  Everyone:  gl.mystery_clues           — View all released clues
             gl.mystery_qualifiers      — View the 5 qualifier slots

Storage: auto_mod_rules table (rule_type = 'mystery_event')
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

import discord
from discord.ext import commands

from database import db
from config import GUILD_ID

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MYSTERY_RULE  = "mystery_event"
MAX_QUALIFIERS = 5

DEV_ID = 858409278473240597

QUALIFY_ROLE_ID  = 1378286435316011099   # Wheel Qualification Role
WINNER_ROLE_ID   = 1486082575817637981   # 1st Place role (meeting with Ronaldo)

# ---------------------------------------------------------------------------
# DB helpers  (same pattern as economy.py)
# ---------------------------------------------------------------------------

async def _get_state(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == MYSTERY_RULE:
            return r.get("config") or {}
    return {
        "word":        None,
        "clues":       [],
        "qualifiers":  [],   # list of {"id": int, "name": str}
        "winner":      None,
        "active":      False,
    }


async def _save_state(guild_id: int, state: dict) -> None:
    await db.upsert_automod_rule(MYSTERY_RULE, True, state, guild_id)


# ---------------------------------------------------------------------------
# Embed helpers  (matching economy.py style)
# ---------------------------------------------------------------------------

def _ok(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ECC71)

def _err(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xE74C3C)

def _info(title: str, desc: str = "") -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=0x7F77DD)
    return e

# ---------------------------------------------------------------------------
# Dev-only check
# ---------------------------------------------------------------------------

def is_dev():
    """Decorator: only your Discord user ID can run this command."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id != DEV_ID:
            await ctx.send(
                embed=_err("Access Denied", "Only the bot developer can use this command.")
            )
            return False
        return True
    return commands.check(predicate)

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class MysteryEventCog(commands.Cog, name="MysteryEvent"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ==========================================================================
    # HOST-ONLY COMMANDS  (only DEV_ID can run these)
    # ==========================================================================

    @commands.command(name="mystery_set")
    @is_dev()
    async def mystery_set(self, ctx: commands.Context, *, word: str) -> None:
        """Set the secret word and activate the event."""
        state = await _get_state(ctx.guild.id)
        state["word"]       = word.strip().lower()
        state["active"]     = True
        state["qualifiers"] = []
        state["winner"]     = None
        await _save_state(ctx.guild.id, state)
        # Confirm in DM so no one sees it in chat
        try:
            await ctx.author.send(
                embed=_ok("Secret word set", f"The word is **{word}**.\nEvent is now **active**.")
            )
            await ctx.message.delete()
        except discord.Forbidden:
            # Fallback: reply ephemerally-ish by deleting after 3s
            msg = await ctx.send(embed=_ok("Word set!", "Check your DMs."))
            await asyncio.sleep(3)
            await msg.delete()

    @commands.command(name="mystery_clue")
    @is_dev()
    async def mystery_clue(self, ctx: commands.Context, *, clue: str) -> None:
        """Add a daily clue for the event."""
        state = await _get_state(ctx.guild.id)
        if not state.get("active"):
            await ctx.send(embed=_err("No active event", "Start one with `gl.mystery_set <word>` first."))
            return

        clues = state.get("clues", [])
        clues.append(clue.strip())
        state["clues"] = clues
        await _save_state(ctx.guild.id, state)

        e = _info(f"🔍 Clue #{len(clues)} released!")
        e.description = f"**{clue}**"
        e.set_footer(text=f"Total clues released: {len(clues)}")
        await ctx.send(embed=e)

    # ==========================================================================
    # AUTO-DETECTION LISTENER
    # ==========================================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Automatically qualify anyone who says the secret word naturally."""
        # Ignore bots, DMs, and messages with no guild
        if message.author.bot or not message.guild:
            return

        state = await _get_state(message.guild.id)

        # Only run when event is active and a word is set
        if not state.get("active") or not state.get("word"):
            return

        secret = state["word"].lower()
        content = message.content.lower()

        # Check the word appears as a whole word (not inside another word)
        if not re.search(rf'\b{re.escape(secret)}\b', content):
            return

        qualifiers = state.get("qualifiers", [])
        user = message.author

        # Skip if already qualified or slots full
        if len(qualifiers) >= MAX_QUALIFIERS:
            return
        if any(q["id"] == user.id for q in qualifiers):
            return

        # Qualify them
        qualifiers.append({"id": user.id, "name": user.display_name})
        state["qualifiers"] = qualifiers
        await _save_state(message.guild.id, state)

        # Give qualifier role
        role = message.guild.get_role(QUALIFY_ROLE_ID)
        if role:
            try:
                await user.add_roles(role, reason="Mystery Event qualifier")
            except discord.Forbidden:
                pass

        slot = len(qualifiers)

        e = _info("🎯 Qualifier found!")
        e.description = (
            f"{user.mention} just said the secret word naturally and has qualified as **slot #{slot}**! 🕵️"
        )
        e.add_field(
            name="Qualifiers so far",
            value="\n".join(f"**#{i+1}** — {q['name']}" for i, q in enumerate(qualifiers)),
            inline=False,
        )
        e.set_footer(text=f"{slot}/{MAX_QUALIFIERS} slots filled")
        await message.channel.send(embed=e)

        # Auto-announce when all 5 slots are filled
        if slot == MAX_QUALIFIERS:
            announce = _info(
                "🔔 All 5 qualifiers found!",
                "The host will spin the wheel to determine the final winner. Stay tuned! 🎡"
            )
            announce.add_field(
                name="The 5 qualifiers",
                value="\n".join(f"**#{i+1}** — {q['name']}" for i, q in enumerate(qualifiers)),
                inline=False,
            )
            await message.channel.send(embed=announce)

    @commands.command(name="mystery_spin")
    @is_dev()
    async def mystery_spin(self, ctx: commands.Context) -> None:
        """Spin the wheel among qualifiers and announce the winner."""
        state = await _get_state(ctx.guild.id)
        qualifiers = state.get("qualifiers", [])

        if not qualifiers:
            await ctx.send(embed=_err("No qualifiers", "No one has qualified yet."))
            return

        winner_data = random.choice(qualifiers)
        winner = ctx.guild.get_member(winner_data["id"])

        state["winner"] = winner_data
        state["active"] = False
        await _save_state(ctx.guild.id, state)

        # Give winner role
        winner_role = ctx.guild.get_role(WINNER_ROLE_ID)
        if winner and winner_role:
            try:
                await winner.add_roles(winner_role, reason="Mystery Event winner")
            except discord.Forbidden:
                pass

        mention = winner.mention if winner else f"**{winner_data['name']}**"

        e = discord.Embed(
            title="🎡 The wheel has spoken!",
            description=(
                f"🎉 Congratulations to {mention}!\n\n"
                f"You are the **Mystery Event Winner** and have won a meeting with Ronaldo!\n"
                f"The host will be in touch with you shortly. 🏆"
            ),
            color=0xF1C40F,
        )
        e.add_field(
            name="The 5 qualifiers were",
            value="\n".join(
                f"{'🏆' if q['id'] == winner_data['id'] else '⭐'} **{q['name']}**"
                for q in qualifiers
            ),
            inline=False,
        )
        e.set_footer(text="Thanks to everyone who participated!")
        await ctx.send(embed=e)

    @commands.command(name="mystery_reset")
    @is_dev()
    async def mystery_reset(self, ctx: commands.Context) -> None:
        """Completely reset the mystery event."""
        blank = {
            "word":       None,
            "clues":      [],
            "qualifiers": [],
            "winner":     None,
            "active":     False,
        }
        await _save_state(ctx.guild.id, blank)
        await ctx.send(embed=_ok("Event reset", "Mystery event has been wiped. You can start fresh with `gl.mystery_set`."))

    @commands.command(name="mystery_status")
    @is_dev()
    async def mystery_status(self, ctx: commands.Context) -> None:
        """(Dev only) View full event status including the secret word."""
        state = await _get_state(ctx.guild.id)
        qualifiers = state.get("qualifiers", [])
        clues      = state.get("clues", [])

        e = _info("🕵️ Mystery Event — Host Status")
        e.add_field(name="Active",       value="Yes" if state.get("active") else "No",          inline=True)
        e.add_field(name="Secret word",  value=f"||{state.get('word') or 'not set'}||",          inline=True)
        e.add_field(name="Qualifiers",   value=f"{len(qualifiers)}/{MAX_QUALIFIERS}",            inline=True)
        e.add_field(
            name="Qualifier list",
            value="\n".join(f"**#{i+1}** — {q['name']}" for i, q in enumerate(qualifiers)) or "None yet",
            inline=False,
        )
        e.add_field(
            name="Clues released",
            value="\n".join(f"**#{i+1}** {c}" for i, c in enumerate(clues)) or "None yet",
            inline=False,
        )
        if state.get("winner"):
            e.add_field(name="Winner", value=state["winner"]["name"], inline=False)

        # Send as DM so the word stays hidden
        try:
            await ctx.author.send(embed=e)
            await ctx.message.delete()
        except discord.Forbidden:
            await ctx.send(embed=e)

    # ==========================================================================
    # PUBLIC COMMANDS  (everyone can use these)
    # ==========================================================================

    @commands.command(name="mystery_clues")
    async def mystery_clues(self, ctx: commands.Context) -> None:
        """View all released clues for the current mystery event."""
        state = await _get_state(ctx.guild.id)

        if not state.get("active") and not state.get("winner"):
            await ctx.send(embed=_err("No event", "There is no mystery event running right now."))
            return

        clues = state.get("clues", [])

        e = _info("🔍 Mystery Event — Clues")
        if not clues:
            e.description = "No clues have been released yet. Check back tomorrow!"
        else:
            e.description = "\n".join(f"**Clue #{i+1}:** {c}" for i, c in enumerate(clues))
            e.set_footer(text="Figure out the word and say it naturally in conversation to qualify!")

        await ctx.send(embed=e)

    @commands.command(name="mystery_qualifiers")
    async def mystery_qualifiers(self, ctx: commands.Context) -> None:
        """View the current qualifier slots."""
        state = await _get_state(ctx.guild.id)

        if not state.get("active") and not state.get("winner"):
            await ctx.send(embed=_err("No event", "There is no mystery event running right now."))
            return

        qualifiers = state.get("qualifiers", [])
        filled     = len(qualifiers)
        remaining  = MAX_QUALIFIERS - filled

        e = _info("🎯 Mystery Event — Qualifier Slots")

        slots = []
        for i in range(MAX_QUALIFIERS):
            if i < filled:
                slots.append(f"**#{i+1}** ✅ {qualifiers[i]['name']}")
            else:
                slots.append(f"**#{i+1}** 🔒 *empty*")

        e.description = "\n".join(slots)

        if state.get("winner"):
            e.add_field(name="🏆 Winner", value=state["winner"]["name"], inline=False)
        elif filled == MAX_QUALIFIERS:
            e.set_footer(text="All slots filled! The wheel will be spun soon.")
        else:
            e.set_footer(text=f"{remaining} slot(s) remaining — say the word naturally to qualify!")

        await ctx.send(embed=e)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CheckFailure):
            return  # already handled inside the check
        log.error("MysteryEventCog error: %s", error)
        await ctx.send(embed=_err("Error", "Something went wrong. Try again later."))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MysteryEventCog(bot))
