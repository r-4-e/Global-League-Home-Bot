"""
cogs/progression.py — Levels, Top Workers, Tax, Lottery for Global League Bot.

Commands:
  gl.level       — view your XP and level
  gl.leaderboard_xp — XP leaderboard
  gl.top_workers — most gl.work uses
  gl.tax_set     — admin: set transaction tax %
  gl.tax         — view current tax rate
  gl.lottery_buy — buy lottery tickets
  gl.lottery_draw — admin: draw lottery winner
  gl.lottery_info — view current lottery pool
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

XP_RULE       = "progression_xp"
WORKER_RULE   = "progression_workers"
TAX_RULE      = "progression_tax"
LOTTERY_RULE  = "progression_lottery"

XP_PER_MESSAGE = 5
XP_COOLDOWN    = 60  # seconds between XP gains per user

LEVELS = [
    (0,    "Rookie"),
    (100,  "Newcomer"),
    (300,  "Member"),
    (600,  "Regular"),
    (1000, "Veteran"),
    (1500, "Elite"),
    (2500, "Champion"),
    (4000, "Legend"),
    (6000, "Mythic"),
    (10000,"Godlike"),
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_xp_data(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == XP_RULE:
            return r.get("config") or {}
    return {}

async def _save_xp_data(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(XP_RULE, True, data, guild_id)

async def _get_worker_data(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == WORKER_RULE:
            return r.get("config") or {}
    return {}

async def _save_worker_data(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(WORKER_RULE, True, data, guild_id)

async def _get_tax(guild_id: int) -> float:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == TAX_RULE:
            return float(r.get("config", {}).get("rate", 0))
    return 0.0

async def _save_tax(guild_id: int, rate: float) -> None:
    await db.upsert_automod_rule(TAX_RULE, True, {"rate": rate}, guild_id)

async def _get_lottery(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == LOTTERY_RULE:
            return r.get("config") or {}
    return {"pool": 0, "tickets": {}, "ticket_price": 100, "active": False}

async def _save_lottery(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(LOTTERY_RULE, True, data, guild_id)


# ---------------------------------------------------------------------------
# Level helper
# ---------------------------------------------------------------------------

def _get_level(xp: int) -> tuple[int, str, int, int]:
    """Returns (level, title, xp_for_current, xp_for_next)."""
    current_level = 0
    current_title = LEVELS[0][1]
    for i, (req, title) in enumerate(LEVELS):
        if xp >= req:
            current_level = i
            current_title = title
        else:
            break
    next_req = LEVELS[current_level + 1][0] if current_level + 1 < len(LEVELS) else None
    curr_req = LEVELS[current_level][0]
    return current_level, current_title, curr_req, next_req


def _xp_bar(xp: int, curr_req: int, next_req: int, length: int = 12) -> str:
    if next_req is None:
        return "█" * length + " MAX"
    progress = (xp - curr_req) / (next_req - curr_req)
    filled   = round(progress * length)
    return "█" * filled + "░" * (length - filled)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ProgressionCog(commands.Cog, name="Progression"):

    def __init__(self, bot):
        self.bot       = bot
        self._xp_cd:   dict[int, float] = {}  # user_id → last_xp_time

    # ── XP listener ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        if message.guild.id != GUILD_ID:
            return

        uid = message.author.id
        now = time.monotonic()

        # Cooldown check
        if now - self._xp_cd.get(uid, 0) < XP_COOLDOWN:
            return
        self._xp_cd[uid] = now

        # Add XP
        xp_data  = await _get_xp_data(message.guild.id)
        uid_str  = str(uid)
        old_xp   = xp_data.get(uid_str, 0)
        new_xp   = old_xp + XP_PER_MESSAGE
        xp_data[uid_str] = new_xp
        await _save_xp_data(message.guild.id, xp_data)

        # Level up check
        old_level, _, _, _ = _get_level(old_xp)
        new_level, new_title, _, _ = _get_level(new_xp)
        if new_level > old_level:
            try:
                e = discord.Embed(
                    title="🎉 Level Up!",
                    description=(
                        f"{message.author.mention} reached **Level {new_level}** — **{new_title}**!\n"
                        f"Total XP: **{new_xp:,}**"
                    ),
                    color=0xF1C40F,
                )
                await message.channel.send(embed=e)
            except discord.Forbidden:
                pass

    # ── gl.level ──────────────────────────────────────────────────────────

    @commands.command(name="level")
    @commands.guild_only()
    async def level(self, ctx, user: discord.Member = None):
        """View your level and XP. Usage: gl.level [@user]"""
        target  = user or ctx.author
        xp_data = await _get_xp_data(ctx.guild.id)
        xp      = xp_data.get(str(target.id), 0)

        level, title, curr_req, next_req = _get_level(xp)
        bar = _xp_bar(xp, curr_req, next_req)

        # Rank
        sorted_users = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)
        rank = next((i+1 for i, (uid, _) in enumerate(sorted_users) if uid == str(target.id)), "N/A")

        e = discord.Embed(
            title=f"⭐ {target.display_name}",
            color=0xF1C40F,
        )
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="🏅 Level",  value=f"**{level}** — {title}",    inline=True)
        e.add_field(name="🏆 Rank",   value=f"**#{rank}**",              inline=True)
        e.add_field(name="✨ XP",     value=f"**{xp:,}**",               inline=True)
        if next_req:
            e.add_field(
                name=f"📊 Progress to Level {level+1}",
                value=f"`{bar}` {xp-curr_req:,} / {next_req-curr_req:,} XP",
                inline=False,
            )
        else:
            e.add_field(name="📊 Progress", value="`████████████` **MAX LEVEL**", inline=False)

        e.set_footer(text=f"Earn XP by chatting  •  1 message = {XP_PER_MESSAGE} XP (60s cooldown)")
        await ctx.send(embed=e)

    @commands.command(name="leaderboard_xp")
    @commands.guild_only()
    async def leaderboard_xp(self, ctx):
        """Top 10 XP leaderboard."""
        xp_data = await _get_xp_data(ctx.guild.id)
        sorted_users = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)[:10]

        e = discord.Embed(title="⭐ XP Leaderboard", color=0xF1C40F)
        medals = ["🥇","🥈","🥉"]
        lines  = []
        for i, (uid, xp) in enumerate(sorted_users):
            level, title, _, _ = _get_level(xp)
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"User {uid}"
            lines.append(f"{medal} **{name}** — Lv.{level} {title} • {xp:,} XP")

        e.description = "\n".join(lines) if lines else "No XP data yet. Start chatting!"
        e.set_footer(text=f"{ctx.guild.name} XP Leaderboard")
        await ctx.send(embed=e)

    # ── gl.top_workers ────────────────────────────────────────────────────

    @commands.command(name="top_workers")
    @commands.guild_only()
    async def top_workers(self, ctx):
        """Leaderboard for most gl.work uses."""
        worker_data = await _get_worker_data(ctx.guild.id)
        sorted_workers = sorted(worker_data.items(), key=lambda x: x[1], reverse=True)[:10]

        e = discord.Embed(title="💼 Top Workers Leaderboard", color=0x3498DB)
        medals = ["🥇","🥈","🥉"]
        lines  = []
        for i, (uid, count) in enumerate(sorted_workers):
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"User {uid}"
            lines.append(f"{medal} **{name}** — {count:,} shifts worked")

        e.description = "\n".join(lines) if lines else "Nobody has worked yet. Use `gl.work`!"
        e.set_footer(text="Based on total gl.work command uses")
        await ctx.send(embed=e)

    # ── gl.tax ────────────────────────────────────────────────────────────

    @commands.command(name="tax")
    @commands.guild_only()
    async def tax(self, ctx):
        """View the current transaction tax rate."""
        rate = await _get_tax(ctx.guild.id)
        if rate == 0:
            await ctx.send(embed=discord.Embed(
                title="💸 Tax", description="No tax is currently applied to transactions.",
                color=0x2ECC71,
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="💸 Tax Rate",
                description=f"A **{rate:.1f}%** tax is applied to all economy transactions.",
                color=0xF39C12,
            ))

    @commands.command(name="tax_set")
    @commands.guild_only()
    async def tax_set(self, ctx, rate: float):
        """Admin: set the transaction tax %. Usage: gl.tax_set <0-50>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return

        if not 0 <= rate <= 50:
            await ctx.send("❌ Tax rate must be between 0% and 50%."); return

        await _save_tax(ctx.guild.id, rate)
        if rate == 0:
            await ctx.send(embed=discord.Embed(
                title="✅ Tax Removed", description="All transactions are now tax-free.",
                color=0x2ECC71,
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="✅ Tax Set",
                description=f"Transaction tax set to **{rate:.1f}%**.\nThis applies to `gl.give`, `gl.rob` proceeds, and marketplace sales.",
                color=0xF39C12,
            ))

    # ── gl.lottery ────────────────────────────────────────────────────────

    @commands.command(name="lottery_info")
    @commands.guild_only()
    async def lottery_info(self, ctx):
        """View the current lottery pool and your tickets."""
        from cogs.economy import _get_config, DEFAULT_CURRENCY
        cfg     = await _get_config(ctx.guild.id)
        sym     = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        lottery = await _get_lottery(ctx.guild.id)

        pool         = lottery.get("pool", 0)
        ticket_price = lottery.get("ticket_price", 100)
        tickets      = lottery.get("tickets", {})
        total_tickets = sum(tickets.values())
        your_tickets  = tickets.get(str(ctx.author.id), 0)
        your_chance   = round((your_tickets / total_tickets) * 100, 1) if total_tickets > 0 else 0

        e = discord.Embed(title="🎟️ Lottery", color=0xF1C40F)
        e.add_field(name="💰 Prize Pool",    value=f"{sym} **{pool:,}**",         inline=True)
        e.add_field(name="🎟 Ticket Price",  value=f"{sym} **{ticket_price:,}**", inline=True)
        e.add_field(name="📊 Total Tickets", value=f"**{total_tickets:,}**",      inline=True)
        e.add_field(name="🎫 Your Tickets",  value=f"**{your_tickets}**",         inline=True)
        e.add_field(name="🍀 Your Chance",   value=f"**{your_chance}%**",         inline=True)
        e.set_footer(text="Use gl.lottery_buy <amount> to buy tickets  •  Admin draws with gl.lottery_draw")
        await ctx.send(embed=e)

    @commands.command(name="lottery_buy")
    @commands.guild_only()
    async def lottery_buy(self, ctx, amount: int = 1):
        """Buy lottery tickets. Usage: gl.lottery_buy [amount]"""
        if amount < 1 or amount > 100:
            await ctx.send("❌ Buy between 1 and 100 tickets at a time."); return

        from cogs.economy import _get_config, _get_balance, _set_balance, _add_audit, DEFAULT_CURRENCY
        cfg     = await _get_config(ctx.guild.id)
        sym     = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        lottery = await _get_lottery(ctx.guild.id)
        ticket_price = lottery.get("ticket_price", 100)
        total_cost   = ticket_price * amount

        data = await _get_balance(ctx.guild.id, ctx.author.id)
        if data["wallet"] < total_cost:
            await ctx.send(embed=discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You need {sym} **{total_cost:,}** but only have {sym} **{data['wallet']:,}** in wallet.",
                color=0xE74C3C,
            ))
            return

        # Deduct cost
        await _set_balance(ctx.guild.id, ctx.author.id, data["wallet"] - total_cost, data["bank"])
        await _add_audit(ctx.guild.id, ctx.author.id, "lottery_buy", -total_cost, f"{amount} tickets")

        # Add tickets to pool
        tickets = lottery.get("tickets", {})
        uid_str = str(ctx.author.id)
        tickets[uid_str] = tickets.get(uid_str, 0) + amount
        lottery["tickets"] = tickets
        lottery["pool"]    = lottery.get("pool", 0) + total_cost
        lottery["active"]  = True
        await _save_lottery(ctx.guild.id, lottery)

        e = discord.Embed(
            title="🎟️ Tickets Purchased!",
            description=(
                f"You bought **{amount}** ticket{'s' if amount > 1 else ''} for {sym} **{total_cost:,}**.\n"
                f"You now have **{tickets[uid_str]}** ticket{'s' if tickets[uid_str] > 1 else ''}.\n\n"
                f"Prize pool: {sym} **{lottery['pool']:,}**"
            ),
            color=0x2ECC71,
        )
        await ctx.send(embed=e)

    @commands.command(name="lottery_draw")
    @commands.guild_only()
    async def lottery_draw(self, ctx):
        """Admin: draw the lottery winner. Usage: gl.lottery_draw"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return

        lottery = await _get_lottery(ctx.guild.id)
        tickets = lottery.get("tickets", {})

        if not tickets:
            await ctx.send("❌ No tickets have been purchased yet."); return

        from cogs.economy import _get_config, _get_balance, _set_balance, _add_audit, DEFAULT_CURRENCY
        cfg = await _get_config(ctx.guild.id)
        sym = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        # Build weighted pool and pick winner
        pool_entries = []
        for uid_str, count in tickets.items():
            pool_entries.extend([uid_str] * count)

        winner_id  = random.choice(pool_entries)
        prize      = lottery.get("pool", 0)
        total_tix  = sum(tickets.values())
        winner_tix = tickets.get(winner_id, 0)
        winner_pct = round((winner_tix / total_tix) * 100, 1)

        # Pay winner
        winner_data = await _get_balance(ctx.guild.id, int(winner_id))
        await _set_balance(ctx.guild.id, int(winner_id), winner_data["wallet"] + prize, winner_data["bank"])
        await _add_audit(ctx.guild.id, int(winner_id), "lottery_win", prize)

        # Reset lottery
        await _save_lottery(ctx.guild.id, {
            "pool": 0, "tickets": {}, "ticket_price": lottery.get("ticket_price", 100), "active": False
        })

        winner = ctx.guild.get_member(int(winner_id))
        winner_name = winner.mention if winner else f"<@{winner_id}>"

        e = discord.Embed(
            title="🎉 Lottery Draw!",
            description=(
                f"🥇 **Winner: {winner_name}**\n\n"
                f"They had **{winner_tix}** tickets ({winner_pct}% chance)\n"
                f"Prize: {sym} **{prize:,}** added to their wallet!"
            ),
            color=0xF1C40F,
        )
        e.add_field(name="🎟 Total Tickets", value=str(total_tix),     inline=True)
        e.add_field(name="👥 Participants",  value=str(len(tickets)),   inline=True)
        e.timestamp = datetime.now(timezone.utc)

        await ctx.send(embed=e)

        # DM winner
        if winner:
            try:
                await winner.send(embed=discord.Embed(
                    title="🎉 You Won the Lottery!",
                    description=f"You won the **{ctx.guild.name}** lottery!\n\nPrize: {sym} **{prize:,}** added to your wallet!",
                    color=0xF1C40F,
                ))
            except discord.Forbidden:
                pass

    @commands.command(name="lottery_setprice")
    @commands.guild_only()
    async def lottery_setprice(self, ctx, price: int):
        """Admin: set the ticket price. Usage: gl.lottery_setprice <price>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        if price < 1:
            await ctx.send("❌ Ticket price must be at least 1."); return
        lottery = await _get_lottery(ctx.guild.id)
        lottery["ticket_price"] = price
        await _save_lottery(ctx.guild.id, lottery)
        from cogs.economy import _get_config, DEFAULT_CURRENCY
        cfg = await _get_config(ctx.guild.id)
        sym = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        await ctx.send(embed=discord.Embed(
            title="✅ Ticket Price Set",
            description=f"Lottery tickets now cost {sym} **{price:,}** each.",
            color=0x2ECC71,
        ))


async def setup(bot):
    await bot.add_cog(ProgressionCog(bot))
