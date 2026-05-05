"""
cogs/puzzle.py — Mystery Puzzle Quest for Global League Bot.

Commands:
  gl.puzzle_setchannel #channel  — [Owner] Set the hint channel
  gl.puzzle_setword <word>       — [Owner] Set the secret word
  gl.puzzle_hint <hint>          — [Owner] Post today's daily hint
  gl.puzzle_status               — [Owner] View current puzzle state
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

OWNER_ID = 858409278473240597

# In-memory state (persists until bot restart)
_puzzle_state = {
    "secret_word":   None,   # current word to guess
    "channel_id":    None,   # hint channel
    "active":        False,  # is puzzle running
    "solved_by":     None,   # user_id who solved it
    "solved_at":     None,   # datetime solved
    "hint_count":    0,      # hints posted so far
    "last_hint_at":  None,   # last hint timestamp
}


def _ist_and_gmt(dt: datetime) -> str:
    """Format a UTC datetime as both IST (+5:30) and GMT."""
    gmt_str = dt.strftime("%d %b %Y, %I:%M %p GMT")
    ist     = dt + timedelta(hours=5, minutes=30)
    ist_str = ist.strftime("%d %b %Y, %I:%M %p IST")
    return f"{ist_str}  •  {gmt_str}"


class PuzzleCog(commands.Cog, name="Puzzle"):

    def __init__(self, bot):
        self.bot = bot

    # ── gl.puzzle_setchannel ──────────────────────────────────────────────

    @commands.command(name="puzzle_setchannel")
    @commands.guild_only()
    async def puzzle_setchannel(self, ctx, channel: discord.TextChannel):
        """[Owner] Set the channel where hints are posted.
        Usage: gl.puzzle_setchannel #channel"""
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ Only the bot owner can use this."); return

        _puzzle_state["channel_id"] = channel.id
        await ctx.send(
            embed=discord.Embed(
                title="✅ Puzzle Channel Set",
                description=f"Hints will be posted in {channel.mention}.",
                color=0x2ECC71,
            )
        )

    # ── gl.puzzle_setword ─────────────────────────────────────────────────

    @commands.command(name="puzzle_setword")
    @commands.guild_only()
    async def puzzle_setword(self, ctx, *, word: str):
        """[Owner] Set the secret word to guess. Deletes your message immediately.
        Usage: gl.puzzle_setword <word>"""
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ Only the bot owner can use this."); return

        # Delete message immediately so word stays secret
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        _puzzle_state["secret_word"]  = word.lower().strip()
        _puzzle_state["active"]       = True
        _puzzle_state["solved_by"]    = None
        _puzzle_state["solved_at"]    = None
        _puzzle_state["hint_count"]   = 0

        # Confirm via DM only so nobody sees it
        try:
            await ctx.author.send(
                embed=discord.Embed(
                    title="🔐 Secret Word Set",
                    description=f"Word set to: **{_puzzle_state['secret_word']}**\nPuzzle is now active.",
                    color=0x2ECC71,
                )
            )
        except discord.Forbidden:
            pass

    # ── gl.puzzle_hint ────────────────────────────────────────────────────

    @commands.command(name="puzzle_hint")
    @commands.guild_only()
    async def puzzle_hint(self, ctx, *, hint: str):
        """[Owner] Post today's daily hint in the puzzle channel.
        Usage: gl.puzzle_hint <hint text>"""
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ Only the bot owner can use this."); return

        if not _puzzle_state.get("channel_id"):
            await ctx.send("❌ No hint channel set. Use `gl.puzzle_setchannel #channel` first."); return

        if not _puzzle_state.get("active"):
            await ctx.send("❌ No active puzzle. Set a word first with `gl.puzzle_setword`."); return

        if _puzzle_state.get("solved_by"):
            await ctx.send("❌ Puzzle already solved! Set a new word with `gl.puzzle_setword`."); return

        channel = ctx.guild.get_channel(_puzzle_state["channel_id"])
        if not channel:
            await ctx.send("❌ Hint channel not found. Use `gl.puzzle_setchannel` again."); return

        # Delete owner's command message
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        _puzzle_state["hint_count"] += 1
        _puzzle_state["last_hint_at"] = datetime.now(timezone.utc)
        hint_num = _puzzle_state["hint_count"]

        e = discord.Embed(
            title=f"🔍 Daily Hint #{hint_num} — The Mystery Puzzle Quest",
            description=hint,
            color=0xF39C12,
        )
        e.set_footer(text="Think you know the answer? Just type it in this channel!")
        e.timestamp = datetime.now(timezone.utc)

        await channel.send(embed=e)

    # ── gl.puzzle_status ──────────────────────────────────────────────────

    @commands.command(name="puzzle_status")
    async def puzzle_status(self, ctx):
        """[Owner] View current puzzle status. Sent as DM."""
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ Only the bot owner can use this."); return

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        word    = _puzzle_state.get("secret_word") or "Not set"
        active  = _puzzle_state.get("active", False)
        solved  = _puzzle_state.get("solved_by")
        ch_id   = _puzzle_state.get("channel_id")
        hints   = _puzzle_state.get("hint_count", 0)
        ch_mention = f"<#{ch_id}>" if ch_id else "Not set"

        e = discord.Embed(title="🔐 Puzzle Status", color=0x5865F2)
        e.add_field(name="Secret Word",  value=f"||{word}||",                      inline=True)
        e.add_field(name="Active",       value="✅ Yes" if active else "❌ No",     inline=True)
        e.add_field(name="Hints Posted", value=str(hints),                         inline=True)
        e.add_field(name="Channel",      value=ch_mention,                         inline=True)

        if solved:
            solved_at = _puzzle_state.get("solved_at")
            e.add_field(name="✅ Solved By", value=f"<@{solved}>", inline=True)
            if solved_at:
                e.add_field(name="⏰ Solved At", value=_ist_and_gmt(solved_at), inline=False)
        else:
            e.add_field(name="Status", value="🔎 Unsolved", inline=True)

        try:
            await ctx.author.send(embed=e)
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Check your DM settings.", delete_after=5)

    # ── Message listener ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # Only watch the puzzle channel
        if message.channel.id != _puzzle_state.get("channel_id"):
            return

        # Puzzle must be active and unsolved
        if not _puzzle_state.get("active"):
            return
        if _puzzle_state.get("solved_by"):
            return

        secret = _puzzle_state.get("secret_word")
        if not secret:
            return

        # Check if the message contains the secret word
        if secret.lower() in message.content.lower():
            now = datetime.now(timezone.utc)
            _puzzle_state["solved_by"] = message.author.id
            _puzzle_state["solved_at"] = now
            _puzzle_state["active"]    = False

            time_str = _ist_and_gmt(now)

            # DM the solver
            try:
                await message.author.send(
                    embed=discord.Embed(
                        title="🎉 You solved the Mystery Puzzle!",
                        description=(
                            f"You guessed the word: **{secret}**\n\n"
                            f"⏰ **Time:** {time_str}\n\n"
                            f"DM the server owner to claim your prize!"
                        ),
                        color=0xF1C40F,
                    )
                )
            except discord.Forbidden:
                pass

            # DM the owner
            owner = message.guild.get_member(OWNER_ID)
            if owner:
                try:
                    await owner.send(
                        embed=discord.Embed(
                            title="🔔 Puzzle Solved!",
                            description=(
                                f"**{message.author}** (`{message.author.id}`) solved the puzzle!\n\n"
                                f"💬 Their message: *{message.content[:200]}*\n"
                                f"⏰ **Time:** {time_str}\n\n"
                                f"Use `gl.puzzle_setword <new word>` to start the next puzzle."
                            ),
                            color=0x2ECC71,
                        )
                    )
                except discord.Forbidden:
                    pass

            # Announce in the channel
            try:
                e = discord.Embed(
                    title="🏆 The Puzzle Has Been Solved!",
                    description=(
                        f"🎉 **{message.author.mention}** cracked the code!\n\n"
                        f"⏰ {time_str}\n\n"
                        f"Stay tuned for the next puzzle!"
                    ),
                    color=0xF1C40F,
                )
                e.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=e)
            except discord.Forbidden:
                pass


async def setup(bot):
    await bot.add_cog(PuzzleCog(bot))
