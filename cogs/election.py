"""
cogs/election.py — Election system. Prefix: gl.
Only user 858409278473240597 can create/end/cancel elections.
"""
from __future__ import annotations
import asyncio, logging
from datetime import datetime, timezone
from typing import Optional
import discord
from discord.ext import commands
from config import GUILD_ID
from database import db

log = logging.getLogger(__name__)
ELECTION_RULE  = "election_data"
ELECTION_ADMIN = 858409278473240597

async def _get_election(guild_id):
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == ELECTION_RULE: return r.get("config") or {}
    return {}

async def _save_election(guild_id, data):
    await db.upsert_automod_rule(ELECTION_RULE, True, data, guild_id)

def _bar(count, total, length=12):
    filled = round((count/total)*length) if total > 0 else 0
    return "█" * filled + "░" * (length-filled)

def _pct(count, total):
    return round((count/total)*100, 1) if total > 0 else 0.0

def _results_embed(election, final=False):
    title      = election.get("title", "Election")
    candidates = election.get("candidates", {})
    votes      = election.get("votes", {})
    ends_at    = election.get("ends_at")
    tally      = {c: 0 for c in candidates}
    for candidate in votes.values():
        if candidate in tally: tally[candidate] += 1
    total = sum(tally.values())
    sorted_c = sorted(tally.items(), key=lambda x: x[1], reverse=True)
    e = discord.Embed(title=f"{'🏆 Final' if final else '📊 Live'} Results — {title}",
                      color=0x2ECC71 if final else 0x3498DB)
    medals = ["🥇","🥈","🥉"]
    for i, (cid, count) in enumerate(sorted_c):
        name  = candidates.get(cid, cid)
        medal = medals[i] if i < 3 else "▫️"
        pct   = _pct(count, total)
        bar   = _bar(count, total)
        label = f"**{name}** — WINNER" if (final and i == 0 and total > 0) else name
        e.add_field(name=f"{medal} {label}", value=f"`{bar}` **{pct}%** ({count} votes)", inline=False)
    e.set_footer(text=f"Total votes: {total}")
    if not final and ends_at:
        e.add_field(name="⏰ Ends", value=f"<t:{int(ends_at)}:R>", inline=False)
    e.timestamp = datetime.now(timezone.utc)
    return e

class VoteView(discord.ui.View):
    def __init__(self, candidates, guild_id, cog):
        super().__init__(timeout=None)
        self.guild_id = guild_id; self.cog = cog
        for cid, name in candidates.items():
            self.add_item(VoteButton(cid, name))

class VoteButton(discord.ui.Button):
    def __init__(self, candidate_id, name):
        super().__init__(label=name, style=discord.ButtonStyle.primary, custom_id=f"vote:{candidate_id}")
        self.candidate_id = candidate_id

    async def callback(self, interaction: discord.Interaction):
        election   = await _get_election(interaction.guild.id)
        if not election or not election.get("active"):
            await interaction.response.send_message("❌ No active election.", ephemeral=True); return
        votes      = election.get("votes", {})
        candidates = election.get("candidates", {})
        if self.candidate_id not in candidates:
            await interaction.response.send_message("❌ Invalid candidate.", ephemeral=True); return
        uid = str(interaction.user.id); already = uid in votes; prev = votes.get(uid)
        votes[uid] = self.candidate_id; election["votes"] = votes
        await _save_election(interaction.guild.id, election)
        name = candidates[self.candidate_id]
        if already and prev != self.candidate_id:
            prev_name = candidates.get(prev, prev)
            await interaction.response.send_message(f"🔄 Vote changed: **{prev_name}** → **{name}**.", ephemeral=True)
        elif already:
            await interaction.response.send_message(f"✅ You already voted for **{name}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Voted for **{name}**.", ephemeral=True)

class ElectionCog(commands.Cog, name="Election"):
    def __init__(self, bot):
        self.bot = bot

    def _is_admin(self, user_id): return user_id == ELECTION_ADMIN

    @commands.command(name="election_create")
    @commands.guild_only()
    async def election_create(self, ctx, *, args: str):
        """Create an election. Usage: gl.election_create Title | Candidate1 | Candidate2 | [hours]"""
        if not self._is_admin(ctx.author.id):
            await ctx.send("❌ You are not authorised to manage elections."); return
        election = await _get_election(ctx.guild.id)
        if election.get("active"):
            await ctx.send("❌ An election is already running. End it first with `gl.election_end`."); return
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            await ctx.send("❌ Usage: `gl.election_create Title | Candidate1 | Candidate2 | [Candidate3] | [hours]`"); return
        title = parts[0]
        # Last part might be hours
        try:
            duration_hours = int(parts[-1]); candidate_parts = parts[1:-1]
        except ValueError:
            duration_hours = 24; candidate_parts = parts[1:]
        candidates = {f"c{i+1}": name for i, name in enumerate(candidate_parts[:5]) if name}
        if len(candidates) < 2:
            await ctx.send("❌ Need at least 2 candidates."); return
        ends_at = datetime.now(timezone.utc).timestamp() + (duration_hours * 3600)
        data = {"active": True, "title": title, "candidates": candidates, "votes": {},
                "ends_at": ends_at, "channel_id": ctx.channel.id, "message_id": None, "created_by": ctx.author.id}
        await _save_election(ctx.guild.id, data)
        e = discord.Embed(title=f"🗳️ {title}",
            description=f"An official election has begun!\n\n**How to vote:** Click a candidate button below.\n\n⏰ **Ends:** <t:{int(ends_at)}:F> (<t:{int(ends_at)}:R>)",
            color=0x5865F2)
        e.add_field(name=f"🏛️ Candidates ({len(candidates)})",
            value="\n".join(f"• **{name}**" for name in candidates.values()), inline=False)
        e.set_footer(text="Official Global League Election  •  One vote per member")
        e.timestamp = datetime.now(timezone.utc)
        view = VoteView(candidates, ctx.guild.id, self)
        msg  = await ctx.send(embed=e, view=view)
        data["message_id"] = msg.id
        await _save_election(ctx.guild.id, data)
        asyncio.create_task(self._auto_end(ctx.guild.id, ends_at, msg.id, ctx.channel.id))

    @commands.command(name="election_vote")
    @commands.guild_only()
    async def election_vote(self, ctx):
        """Vote in the active election."""
        election = await _get_election(ctx.guild.id)
        if not election or not election.get("active"):
            await ctx.send("❌ No active election right now."); return
        candidates = election.get("candidates", {})
        e = discord.Embed(title=f"🗳️ Vote — {election.get('title', 'Election')}",
            description="Select your candidate below. You can change your vote before the election ends.",
            color=0x5865F2)
        e.add_field(name="Candidates", value="\n".join(f"• **{name}**" for name in candidates.values()), inline=False)
        await ctx.send(embed=e, view=VoteView(candidates, ctx.guild.id, self))

    @commands.command(name="election_results")
    @commands.guild_only()
    async def election_results(self, ctx):
        """View live election results."""
        election = await _get_election(ctx.guild.id)
        if not election:
            await ctx.send("❌ No election data found."); return
        await ctx.send(embed=_results_embed(election, final=not election.get("active")))

    @commands.command(name="election_end")
    @commands.guild_only()
    async def election_end(self, ctx):
        """End the active election and announce results."""
        if not self._is_admin(ctx.author.id):
            await ctx.send("❌ You are not authorised to manage elections."); return
        election = await _get_election(ctx.guild.id)
        if not election or not election.get("active"):
            await ctx.send("❌ No active election to end."); return
        await self._finalise(ctx.guild, election)
        await ctx.send("✅ Election ended and results announced.")

    @commands.command(name="election_cancel")
    @commands.guild_only()
    async def election_cancel(self, ctx):
        """Cancel the active election."""
        if not self._is_admin(ctx.author.id):
            await ctx.send("❌ You are not authorised to manage elections."); return
        election = await _get_election(ctx.guild.id)
        if not election or not election.get("active"):
            await ctx.send("❌ No active election to cancel."); return
        election["active"] = False
        await _save_election(ctx.guild.id, election)
        ch_id = election.get("channel_id"); msg_id = election.get("message_id")
        if ch_id and msg_id:
            ch = ctx.guild.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(embed=discord.Embed(title=f"🚫 Election Cancelled — {election.get('title','Election')}",
                        description="This election was cancelled by an administrator.", color=0xE74C3C), view=None)
                except (discord.NotFound, discord.Forbidden): pass
        await ctx.send("✅ Election cancelled.")

    async def _finalise(self, guild, election):
        election["active"] = False
        await _save_election(guild.id, election)
        candidates = election.get("candidates", {})
        votes      = election.get("votes", {})
        tally      = {c: 0 for c in candidates}
        for candidate in votes.values():
            if candidate in tally: tally[candidate] += 1
        total      = sum(tally.values())
        winner_id  = max(tally, key=tally.get) if tally else None
        winner_name = candidates.get(winner_id, "Unknown") if winner_id else "No votes cast"
        winner_pct  = _pct(tally.get(winner_id, 0), total)
        results     = _results_embed(election, final=True)
        ch_id  = election.get("channel_id"); msg_id = election.get("message_id")
        if ch_id and msg_id:
            ch = guild.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(embed=results, view=None)
                except (discord.NotFound, discord.Forbidden): pass
                if total > 0:
                    announce = discord.Embed(title="🏆 Election Complete!",
                        description=(f"**{election.get('title','Election')}** has ended.\n\n"
                                     f"🥇 **Winner: {winner_name}**\n"
                                     f"with **{tally.get(winner_id,0)} votes** ({winner_pct}%)\n\n"
                                     f"Total votes: **{total}**"),
                        color=0xF1C40F)
                    announce.timestamp = datetime.now(timezone.utc)
                    try: await ch.send(embed=announce)
                    except discord.Forbidden: pass

    async def _auto_end(self, guild_id, ends_at, msg_id, ch_id):
        remaining = ends_at - datetime.now(timezone.utc).timestamp()
        if remaining > 0: await asyncio.sleep(remaining)
        guild    = self.bot.get_guild(guild_id)
        election = await _get_election(guild_id)
        if guild and election and election.get("active"):
            await self._finalise(guild, election)

async def setup(bot):
    await bot.add_cog(ElectionCog(bot))
