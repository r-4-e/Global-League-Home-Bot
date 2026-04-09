"""
cogs/election.py — Professional Election System for Global League Bot.

Only user ID 858409278473240597 can create, end, and cancel elections.
Members vote via button UI. Live results with progress bars.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db

log = logging.getLogger(__name__)

ELECTION_RULE  = "election_data"
ELECTION_ADMIN = 858409278473240597


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_election(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == ELECTION_RULE:
            return r.get("config") or {}
    return {}


async def _save_election(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(ELECTION_RULE, True, data, guild_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(count: int, total: int, length: int = 12) -> str:
    if total == 0:
        filled = 0
    else:
        filled = round((count / total) * length)
    return "█" * filled + "░" * (length - filled)


def _pct(count: int, total: int) -> float:
    return round((count / total) * 100, 1) if total > 0 else 0.0


def _results_embed(election: dict, final: bool = False) -> discord.Embed:
    title    = election.get("title", "Election")
    candidates = election.get("candidates", {})
    votes    = election.get("votes", {})
    ends_at  = election.get("ends_at")

    # Tally
    tally: dict[str, int] = {c: 0 for c in candidates}
    for candidate in votes.values():
        if candidate in tally:
            tally[candidate] += 1

    total = sum(tally.values())
    sorted_candidates = sorted(tally.items(), key=lambda x: x[1], reverse=True)

    color = 0x2ECC71 if final else 0x3498DB
    header = "🏆 Election Results" if final else "📊 Live Election Results"

    e = discord.Embed(title=f"{header} — {title}", color=color)
    e.set_footer(text=f"Total votes cast: {total}")

    for i, (candidate_id, count) in enumerate(sorted_candidates):
        name  = candidates.get(candidate_id, candidate_id)
        bar   = _bar(count, total)
        pct   = _pct(count, total)
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "▫️"

        if final and i == 0 and total > 0:
            e.add_field(
                name=f"{medal} **{name}** — WINNER",
                value=f"`{bar}` **{pct}%** ({count} votes)",
                inline=False,
            )
        else:
            e.add_field(
                name=f"{medal} {name}",
                value=f"`{bar}` {pct}% ({count} votes)",
                inline=False,
            )

    if not final and ends_at:
        e.add_field(
            name="⏰ Ends",
            value=f"<t:{int(ends_at)}:R>",
            inline=False,
        )

    e.timestamp = datetime.now(timezone.utc)
    return e


# ---------------------------------------------------------------------------
# Vote View
# ---------------------------------------------------------------------------

class VoteView(discord.ui.View):
    def __init__(self, candidates: dict, guild_id: int, cog: "ElectionCog") -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.cog      = cog
        for candidate_id, name in candidates.items():
            self.add_item(VoteButton(candidate_id, name))


class VoteButton(discord.ui.Button):
    def __init__(self, candidate_id: str, name: str) -> None:
        super().__init__(
            label=name,
            style=discord.ButtonStyle.primary,
            custom_id=f"vote:{candidate_id}",
        )
        self.candidate_id = candidate_id

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoteView = self.view  # type: ignore[assignment]
        guild_id  = interaction.guild.id
        uid       = str(interaction.user.id)

        election = await _get_election(guild_id)

        if not election or not election.get("active"):
            await interaction.response.send_message(
                "❌ There is no active election right now.", ephemeral=True
            )
            return

        votes      = election.get("votes", {})
        candidates = election.get("candidates", {})

        if self.candidate_id not in candidates:
            await interaction.response.send_message("❌ Invalid candidate.", ephemeral=True)
            return

        already_voted = uid in votes
        previous      = votes.get(uid)

        votes[uid]         = self.candidate_id
        election["votes"]  = votes
        await _save_election(guild_id, election)

        candidate_name = candidates[self.candidate_id]

        if already_voted and previous != self.candidate_id:
            prev_name = candidates.get(previous, previous)
            await interaction.response.send_message(
                f"🔄 Your vote has been changed from **{prev_name}** to **{candidate_name}**.",
                ephemeral=True,
            )
        elif already_voted:
            await interaction.response.send_message(
                f"✅ You have already voted for **{candidate_name}**.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"✅ Your vote for **{candidate_name}** has been recorded.",
                ephemeral=True,
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ElectionCog(commands.Cog, name="Election"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_admin(self, user_id: int) -> bool:
        return user_id == ELECTION_ADMIN

    # ── /election_create ──────────────────────────────────────────────────

    @app_commands.command(
        name="election_create",
        description="Create a new server election.",
    )
    @app_commands.describe(
        title="Election title e.g. 'Server President 2025'",
        candidate1="First candidate name",
        candidate2="Second candidate name",
        candidate3="Third candidate (optional)",
        candidate4="Fourth candidate (optional)",
        candidate5="Fifth candidate (optional)",
        duration_hours="How long the election runs in hours (default 24)",
        channel="Channel to post the election in (default: current)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def election_create(
        self,
        interaction: discord.Interaction,
        title: str,
        candidate1: str,
        candidate2: str,
        candidate3: Optional[str] = None,
        candidate4: Optional[str] = None,
        candidate5: Optional[str] = None,
        duration_hours: int = 24,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not authorised to manage elections.", ephemeral=True
            )
            return

        election = await _get_election(interaction.guild.id)
        if election.get("active"):
            await interaction.response.send_message(
                "❌ An election is already running. End it first with `/election_end`.",
                ephemeral=True,
            )
            return

        # Build candidates dict
        raw = [candidate1, candidate2, candidate3, candidate4, candidate5]
        candidates = {}
        for i, name in enumerate(raw):
            if name:
                candidates[f"c{i+1}"] = name.strip()

        ends_at  = datetime.now(timezone.utc).timestamp() + (duration_hours * 3600)
        target_ch = channel or interaction.channel

        # Save election data
        data = {
            "active":     True,
            "title":      title,
            "candidates": candidates,
            "votes":      {},
            "ends_at":    ends_at,
            "channel_id": target_ch.id,
            "message_id": None,
            "created_by": interaction.user.id,
        }
        await _save_election(interaction.guild.id, data)

        # Build election embed
        e = discord.Embed(
            title=f"🗳️ {title}",
            description=(
                f"An official election has begun!\n\n"
                f"**How to vote:** Click a candidate button below.\n"
                f"You can change your vote at any time before the election ends.\n\n"
                f"⏰ **Ends:** <t:{int(ends_at)}:F> (<t:{int(ends_at)}:R>)"
            ),
            color=0x5865F2,
        )
        e.add_field(
            name=f"🏛️ Candidates ({len(candidates)})",
            value="\n".join(f"• **{name}**" for name in candidates.values()),
            inline=False,
        )
        e.set_footer(text="Official Global League Election  •  One vote per member")
        e.timestamp = datetime.now(timezone.utc)

        view = VoteView(candidates, interaction.guild.id, self)

        await interaction.response.send_message("✅ Election created!", ephemeral=True)

        msg = await target_ch.send(embed=e, view=view)

        # Save message ID for later editing
        data["message_id"] = msg.id
        await _save_election(interaction.guild.id, data)

        # Schedule auto-end
        asyncio.create_task(
            self._auto_end(interaction.guild.id, ends_at, msg.id, target_ch.id)
        )

    # ── /election_vote ────────────────────────────────────────────────────

    @app_commands.command(name="election_vote", description="Vote in the active election.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def election_vote(self, interaction: discord.Interaction) -> None:
        election = await _get_election(interaction.guild.id)

        if not election or not election.get("active"):
            await interaction.response.send_message(
                "❌ There is no active election right now.", ephemeral=True
            )
            return

        candidates = election.get("candidates", {})
        ch_id      = election.get("channel_id")
        ch         = interaction.guild.get_channel(ch_id) if ch_id else None

        e = discord.Embed(
            title=f"🗳️ Vote — {election.get('title', 'Election')}",
            description="Select your candidate below. You can change your vote at any time.",
            color=0x5865F2,
        )
        e.add_field(
            name="Candidates",
            value="\n".join(f"• **{name}**" for name in candidates.values()),
            inline=False,
        )
        if ch:
            e.set_footer(text=f"Election panel in #{ch.name}")

        view = VoteView(candidates, interaction.guild.id, self)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    # ── /election_results ─────────────────────────────────────────────────

    @app_commands.command(name="election_results", description="View live election results.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def election_results(self, interaction: discord.Interaction) -> None:
        election = await _get_election(interaction.guild.id)

        if not election:
            await interaction.response.send_message(
                "❌ No election data found.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=_results_embed(election, final=not election.get("active")),
            ephemeral=True,
        )

    # ── /election_end ─────────────────────────────────────────────────────

    @app_commands.command(name="election_end", description="End the active election and announce results.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def election_end(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not authorised to manage elections.", ephemeral=True
            )
            return

        election = await _get_election(interaction.guild.id)

        if not election or not election.get("active"):
            await interaction.response.send_message(
                "❌ No active election to end.", ephemeral=True
            )
            return

        await self._finalise(interaction.guild, election)
        await interaction.response.send_message(
            "✅ Election ended and results announced.", ephemeral=True
        )

    # ── /election_cancel ──────────────────────────────────────────────────

    @app_commands.command(name="election_cancel", description="Cancel the active election with no results.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def election_cancel(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not authorised to manage elections.", ephemeral=True
            )
            return

        election = await _get_election(interaction.guild.id)

        if not election or not election.get("active"):
            await interaction.response.send_message(
                "❌ No active election to cancel.", ephemeral=True
            )
            return

        election["active"] = False
        await _save_election(interaction.guild.id, election)

        # Edit original message if possible
        ch_id  = election.get("channel_id")
        msg_id = election.get("message_id")
        if ch_id and msg_id:
            ch = interaction.guild.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    cancelled_embed = discord.Embed(
                        title=f"🚫 Election Cancelled — {election.get('title', 'Election')}",
                        description="This election has been cancelled by an administrator.",
                        color=0xE74C3C,
                    )
                    await msg.edit(embed=cancelled_embed, view=None)
                except (discord.NotFound, discord.Forbidden):
                    pass

        await interaction.response.send_message(
            "✅ Election cancelled.", ephemeral=True
        )

    # ── Internal finalise ─────────────────────────────────────────────────

    async def _finalise(self, guild: discord.Guild, election: dict) -> None:
        election["active"] = False
        await _save_election(guild.id, election)

        results = _results_embed(election, final=True)

        # Determine winner
        candidates = election.get("candidates", {})
        votes      = election.get("votes", {})
        tally: dict[str, int] = {c: 0 for c in candidates}
        for candidate in votes.values():
            if candidate in tally:
                tally[candidate] += 1

        total = sum(tally.values())
        winner_id   = max(tally, key=tally.get) if tally else None
        winner_name = candidates.get(winner_id, "Unknown") if winner_id else "No votes cast"
        winner_pct  = _pct(tally.get(winner_id, 0), total)

        # Edit original message
        ch_id  = election.get("channel_id")
        msg_id = election.get("message_id")
        if ch_id and msg_id:
            ch = guild.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(embed=results, view=None)
                except (discord.NotFound, discord.Forbidden):
                    pass

                # Send winner announcement
                if total > 0:
                    announce = discord.Embed(
                        title="🏆 Election Complete!",
                        description=(
                            f"**{election.get('title', 'Election')}** has ended.\n\n"
                            f"🥇 **Winner: {winner_name}**\n"
                            f"with **{tally.get(winner_id, 0)} votes** ({winner_pct}%)\n\n"
                            f"Total votes cast: **{total}**"
                        ),
                        color=0xF1C40F,
                    )
                    announce.timestamp = datetime.now(timezone.utc)
                    try:
                        await ch.send(embed=announce)
                    except discord.Forbidden:
                        pass
                else:
                    try:
                        await ch.send(
                            embed=discord.Embed(
                                title="🗳️ Election Ended",
                                description=f"**{election.get('title')}** ended with no votes cast.",
                                color=0x95A5A6,
                            )
                        )
                    except discord.Forbidden:
                        pass

    # ── Auto end task ─────────────────────────────────────────────────────

    async def _auto_end(
        self,
        guild_id: int,
        ends_at: float,
        msg_id: int,
        ch_id: int,
    ) -> None:
        import time
        remaining = ends_at - datetime.now(timezone.utc).timestamp()
        if remaining > 0:
            await asyncio.sleep(remaining)

        guild    = self.bot.get_guild(guild_id)
        election = await _get_election(guild_id)

        if guild and election and election.get("active"):
            await self._finalise(guild, election)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("ElectionCog error: %s", error)
        msg = "❌ Something went wrong. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ElectionCog(bot))
