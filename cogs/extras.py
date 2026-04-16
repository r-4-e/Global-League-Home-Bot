"""
cogs/extras.py — Extra utility commands for Global League Bot.

Commands:
  gl.lookup      — full profile: cases + notes + userinfo in one embed
  gl.warn_history — filtered warns-only history for a user
  gl.dice        — roll any dice e.g. gl.dice 2d6
  gl.lyrics      — search song info via lyrics.ovh (no API key)
  gl.counting_setup — setup a counting channel
"""

from __future__ import annotations

import json
import logging
import random
import re

import aiohttp
import discord
from discord.ext import commands

from database import db
from utils.permissions import gate_warn

log = logging.getLogger(__name__)


class ExtrasCog(commands.Cog, name="Extras"):

    def __init__(self, bot):
        self.bot = bot
        # counting: { guild_id: { channel_id, current, last_user_id } }
        self._counting: dict[int, dict] = {}

    # ── gl.lookup ─────────────────────────────────────────────────────────

    @commands.command(name="lookup")
    @commands.guild_only()
    async def lookup(self, ctx, user: discord.Member):
        """Full profile: cases, notes, and member info in one embed.
        Usage: gl.lookup @user"""
        if not await gate_warn(ctx):
            return

        async with ctx.typing():
            all_cases, total = await db.get_cases(user.id, ctx.guild.id, page=1, page_size=500)
            notes = await db.get_notes(user.id, ctx.guild.id)

        warns    = [c for c in all_cases if c.get("action") == "WARN"    and c.get("active")]
        bans     = [c for c in all_cases if c.get("action") == "BAN"]
        kicks    = [c for c in all_cases if c.get("action") == "KICK"]
        timeouts = [c for c in all_cases if c.get("action") == "TIMEOUT"]
        mutes    = [c for c in all_cases if c.get("action") == "MUTE"]

        # Status colour
        if total == 0:         color = 0x2ECC71
        elif total <= 2:       color = 0xF1C40F
        elif total <= 5:       color = 0xF39C12
        else:                  color = 0xE74C3C

        e = discord.Embed(
            title=f"🔍 Lookup — {user}",
            color=color,
        )
        e.set_thumbnail(url=user.display_avatar.url)

        # Identity
        e.add_field(name="🆔 User ID",       value=f"`{user.id}`",                    inline=True)
        e.add_field(name="🏷 Nickname",       value=user.nick or "None",               inline=True)
        e.add_field(name="📅 Joined",         value=f"<t:{int(user.joined_at.timestamp())}:R>" if user.joined_at else "Unknown", inline=True)
        e.add_field(name="🗓 Account Age",    value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)

        # Moderation summary
        e.add_field(
            name="⚒️ Mod Summary",
            value=(
                f"⚠️ Active Warns: **{len(warns)}**\n"
                f"🔨 Bans: **{len(bans)}**\n"
                f"👢 Kicks: **{len(kicks)}**\n"
                f"⏱ Timeouts: **{len(timeouts)}**\n"
                f"🔇 Mutes: **{len(mutes)}**\n"
                f"📋 Total Cases: **{total}**\n"
                f"📝 Staff Notes: **{len(notes)}**"
            ),
            inline=True,
        )

        # Last 3 cases
        if all_cases:
            recent = all_cases[:3]
            lines  = []
            for c in recent:
                ts  = c.get("timestamp","")[:10]
                act = c.get("action","?")
                rsn = (c.get("reason") or "No reason")[:40]
                lines.append(f"`{ts}` **{act}** — {rsn}")
            e.add_field(name="📋 Recent Cases", value="\n".join(lines), inline=False)

        # Last note
        if notes:
            n = notes[0]
            e.add_field(
                name="📝 Latest Note",
                value=f"{n['content'][:150]}\n*— <@{n['moderator_id']}> {n.get('timestamp','')[:10]}*",
                inline=False,
            )

        # Roles
        roles     = [r.mention for r in reversed(user.roles) if r.id != ctx.guild.id][:10]
        roles_str = " ".join(roles) if roles else "None"
        e.add_field(name=f"🎭 Roles [{len(user.roles)-1}]", value=roles_str, inline=False)

        e.set_footer(text=f"Requested by {ctx.author}")
        e.timestamp = discord.utils.utcnow()
        await ctx.send(embed=e)

    # ── gl.warn_history ───────────────────────────────────────────────────

    @commands.command(name="warn_history")
    @commands.guild_only()
    async def warn_history(self, ctx, user: discord.Member, page: int = 1):
        """View warns-only history for a user.
        Usage: gl.warn_history @user [page]"""
        if not await gate_warn(ctx):
            return

        all_cases, _ = await db.get_cases(user.id, ctx.guild.id, page=1, page_size=500)
        warns        = [c for c in all_cases if c.get("action") == "WARN"]

        if not warns:
            await ctx.send(embed=discord.Embed(
                title="⚠️ Warn History",
                description=f"{user.mention} has no warnings.",
                color=0x2ECC71,
            ))
            return

        page_size   = 5
        total_pages = max(1, -(-len(warns) // page_size))
        page        = max(1, min(page, total_pages))
        page_warns  = warns[(page-1)*page_size : page*page_size]

        active_count   = sum(1 for w in warns if w.get("active"))
        inactive_count = sum(1 for w in warns if not w.get("active"))

        e = discord.Embed(
            title=f"⚠️ Warning History — {user}",
            color=0xF39C12,
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.description = (
            f"**Active warnings:** {active_count}\n"
            f"**Removed warnings:** {inactive_count}\n"
            f"**Total:** {len(warns)}"
        )

        for w in page_warns:
            ts     = w.get("timestamp","")[:10]
            status = "🟢 Active" if w.get("active") else "🔴 Removed"
            reason = w.get("reason") or "No reason provided."
            e.add_field(
                name=f"Case #{w['case_id']}  ({ts})  {status}",
                value=f"**Reason:** {reason}\n**Mod:** <@{w['moderator_id']}>",
                inline=False,
            )

        e.set_footer(text=f"Page {page}/{total_pages}  •  Use gl.warn_history @user {page+1} for next page")
        await ctx.send(embed=e)

    # ── gl.dice ───────────────────────────────────────────────────────────

    @commands.command(name="dice")
    async def dice(self, ctx, notation: str = "1d6"):
        """Roll dice. Usage: gl.dice [NdN] e.g. gl.dice 2d6 gl.dice 1d20"""
        notation = notation.lower().strip()
        match = re.fullmatch(r"(\d+)d(\d+)", notation)
        if not match:
            await ctx.send("❌ Use dice notation like `1d6`, `2d10`, `3d20` (max 100d100).")
            return

        num_dice = int(match.group(1))
        num_sides = int(match.group(2))

        if num_dice < 1 or num_dice > 100:
            await ctx.send("❌ Number of dice must be between 1 and 100."); return
        if num_sides < 2 or num_sides > 10000:
            await ctx.send("❌ Number of sides must be between 2 and 10,000."); return

        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)

        color = 0xF1C40F
        if num_dice == 1:
            if rolls[0] == num_sides: color = 0x2ECC71  # nat max
            elif rolls[0] == 1:       color = 0xE74C3C  # nat 1

        e = discord.Embed(title=f"🎲 {notation.upper()}", color=color)

        if num_dice == 1:
            e.description = f"# **{rolls[0]}**"
            if rolls[0] == num_sides: e.description += "\n✨ **Natural Max!**"
            elif rolls[0] == 1:       e.description += "\n💀 **Critical Fail!**"
        else:
            rolls_str = " + ".join(f"**{r}**" for r in rolls[:20])
            if len(rolls) > 20: rolls_str += f" *...+{len(rolls)-20} more*"
            e.add_field(name="Rolls",  value=rolls_str, inline=False)
            e.add_field(name="Total",  value=f"**{total}**", inline=True)
            e.add_field(name="Avg",    value=f"**{total/num_dice:.1f}**", inline=True)
            e.add_field(name="Min/Max",value=f"**{min(rolls)}** / **{max(rolls)}**", inline=True)

        e.set_footer(text=f"Rolled by {ctx.author}")
        await ctx.send(embed=e)

    # ── gl.lyrics ─────────────────────────────────────────────────────────

    @commands.command(name="lyrics")
    async def lyrics(self, ctx, *, query: str):
        """Search for song information. Usage: gl.lyrics <artist - song>
        Tip: Use format 'Artist - Song Title' for best results."""
        async with ctx.typing():
            # Parse artist/title from query
            if " - " in query:
                parts  = query.split(" - ", 1)
                artist = parts[0].strip()
                title  = parts[1].strip()
            else:
                artist = ""
                title  = query.strip()

            # Use lyrics.ovh API (free, no key)
            if artist:
                url = f"https://api.lyrics.ovh/v1/{artist}/{title}"
            else:
                # Try to search using the full query
                url = f"https://api.lyrics.ovh/suggest/{query}"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=8),
                        headers={"User-Agent": "GlobalLeagueBot/1.0"},
                    ) as resp:
                        data = await resp.json()
            except Exception as exc:
                log.error("lyrics fetch error: %s", exc)
                await ctx.send("❌ Could not reach the lyrics service. Try again later.")
                return

        # Handle suggest response (no artist given)
        if "data" in data:
            results = data.get("data", [])
            if not results:
                await ctx.send(f"❌ No results found for `{query}`.")
                return
            top = results[0]
            artist = top.get("artist", {}).get("name", "Unknown")
            title  = top.get("title", "Unknown")
            album  = top.get("album", {}).get("title", "Unknown")

            e = discord.Embed(
                title=f"🎵 {title}",
                description=f"**Artist:** {artist}\n**Album:** {album}",
                color=0x1DB954,
            )
            if len(results) > 1:
                other = "\n".join(
                    f"• **{r.get('artist',{}).get('name','')}** — {r.get('title','')}"
                    for r in results[1:4]
                )
                e.add_field(name="Other results", value=other, inline=False)
            e.add_field(
                name="📖 Full Lyrics",
                value=f"Search on [Genius](https://genius.com/search?q={query.replace(' ', '+')}) or [AZLyrics](https://search.azlyrics.com/search.php?q={query.replace(' ', '+')})",
                inline=False,
            )
            e.set_footer(text="Lyrics display is not supported to respect copyright  •  Use the links above")
            await ctx.send(embed=e)
            return

        # Direct lyrics response
        if "error" in data:
            await ctx.send(f"❌ `{artist} - {title}` not found. Try: `gl.lyrics Artist - Song Title`")
            return

        # We have lyrics — don't display them (copyright), just show metadata
        e = discord.Embed(
            title=f"🎵 {title}",
            description=f"**Artist:** {artist}",
            color=0x1DB954,
        )
        e.add_field(
            name="📖 Find Lyrics",
            value=(
                f"[Genius](https://genius.com/search?q={query.replace(' ', '+')})  •  "
                f"[AZLyrics](https://search.azlyrics.com/search.php?q={query.replace(' ', '+')})"
            ),
            inline=False,
        )
        e.set_footer(text="Lyrics cannot be displayed directly  •  Click the links above to read them")
        await ctx.send(embed=e)

    # ── gl.counting_setup ─────────────────────────────────────────────────

    @commands.command(name="counting_setup")
    @commands.guild_only()
    async def counting_setup(self, ctx, channel: discord.TextChannel = None):
        """Setup a counting channel. Usage: gl.counting_setup [#channel]"""
        from utils.permissions import check_invoker_permission
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok:
            await ctx.send(msg); return

        target = channel or ctx.channel
        self._counting[ctx.guild.id] = {
            "channel_id":   target.id,
            "current":      0,
            "last_user_id": None,
        }

        e = discord.Embed(
            title="🔢 Counting Channel Setup",
            description=(
                f"Counting channel set to {target.mention}!\n\n"
                f"**Rules:**\n"
                f"• Members take turns counting up from 1\n"
                f"• You cannot count twice in a row\n"
                f"• Wrong number resets the count back to 0\n"
                f"• Bot will react ✅ for correct, ❌ for wrong"
            ),
            color=0x2ECC71,
        )
        await ctx.send(embed=e)
        await target.send(embed=discord.Embed(
            title="🔢 Counting Channel",
            description="Count up from **1**! Take turns — no consecutive counts.\nStart with **1**!",
            color=0x3498DB,
        ))

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return

        guild_id = message.guild.id
        counting = self._counting.get(guild_id)
        if not counting:
            return
        if message.channel.id != counting["channel_id"]:
            return

        content = message.content.strip()
        try:
            number = int(content)
        except ValueError:
            return  # Not a number — ignore

        expected      = counting["current"] + 1
        last_user_id  = counting["last_user_id"]

        # Same person counted twice
        if message.author.id == last_user_id:
            counting["current"]      = 0
            counting["last_user_id"] = None
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ {message.author.mention}, you can't count twice in a row! Count reset to **0**. Start again from **1**."
            )
            return

        # Wrong number
        if number != expected:
            counting["current"]      = 0
            counting["last_user_id"] = None
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ {message.author.mention} ruined it! Expected **{expected}**, got **{number}**. Count reset to **0**. Start again from **1**."
            )
            return

        # Correct!
        counting["current"]      = number
        counting["last_user_id"] = message.author.id
        await message.add_reaction("✅")

        # Milestone reactions
        if number % 100 == 0:
            await message.channel.send(f"🎉 **{number}!** Amazing counting everyone! Keep it up!")
        elif number % 50 == 0:
            await message.add_reaction("🎯")


async def setup(bot):
    await bot.add_cog(ExtrasCog(bot))
