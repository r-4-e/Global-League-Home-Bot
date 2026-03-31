"""
cogs/economy.py — Full Economy System for Elura.

Commands:
  User:      /balance, /money, /leaderboard, /deposit, /withdraw, /give
  Work:      /work, /crime, /rob, /claim
  Games:     /blackjack, /roulette, /slots, /fight, /roll, /pick
  Store:     /store, /buy, /sell, /inventory, /use_item
  Admin:     /add_money, /remove_money, /set_money, /reset_economy
             /add_store_item, /remove_store_item, /edit_store_item
             /set_currency, /set_start_balance, /set_cooldown, /set_payout
             /add_money_role, /remove_money_role
  Stats:     /economy_stats, /money_audit_log

Storage: auto_mod_rules table (rule_type = 'economy_config')
         cases table repurposed for audit log
         users + custom JSONB per user via auto_mod_rules
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

CONFIG_RULE    = "economy_config"
BALANCE_RULE   = "economy_balances"
ITEMS_RULE     = "economy_store"
INVENTORY_RULE = "economy_inventory"
COOLDOWN_RULE  = "economy_cooldowns"
AUDIT_RULE     = "economy_audit"
MILESTONE_RULE = "economy_milestones"

# Balance milestones → (threshold, role_name, hardcoded_role_id)
MILESTONES = [
    (1_000_000_000_000_000, "quadrillionaire", 1485558039456125019),
    (1_000_000_000_000,     "trillionaire",    1485557902625210458),
    (1_000_000_000,         "billionaire",     1485557727999688864),
    (1_000_000,             "millionaire",     1485557662308630528),
]

# Max balance a user can hold
MAX_BALANCE = 1_000_000_000_000_000

# ── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_CURRENCY     = "🪙"
DEFAULT_CURRENCY_NAME = "coins"
DEFAULT_START_BAL    = 100
DEFAULT_COOLDOWNS    = {
    "work":  3600,   # 1 hour
    "crime": 7200,   # 2 hours
    "rob":   3600,   # 1 hour
    "claim": 86400,  # 24 hours
}
DEFAULT_PAYOUTS = {
    "work_min":  50,
    "work_max":  200,
    "crime_min": 100,
    "crime_max": 500,
    "crime_fail_chance": 0.35,
    "rob_min":   50,
    "rob_max":   300,
    "rob_fail_chance":   0.40,
    "claim_amount":      100,
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_config(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == CONFIG_RULE:
            return r.get("config") or {}
    return {}


async def _save_config(guild_id: int, update: dict) -> None:
    existing = await _get_config(guild_id)
    existing.update(update)
    await db.upsert_automod_rule(CONFIG_RULE, True, existing, guild_id)


async def _get_all_balances(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == BALANCE_RULE:
            return r.get("config") or {}
    return {}


async def _save_balances(guild_id: int, balances: dict) -> None:
    await db.upsert_automod_rule(BALANCE_RULE, True, balances, guild_id)


async def _get_balance(guild_id: int, user_id: int, default: int = DEFAULT_START_BAL) -> int:
    balances = await _get_all_balances(guild_id)
    uid = str(user_id)
    if uid not in balances:
        # New user — give start balance from config
        cfg = await _get_config(guild_id)
        default = int(cfg.get("start_balance", DEFAULT_START_BAL))
        balances[uid] = {"wallet": default, "bank": 0}
        await _save_balances(guild_id, balances)
    data = balances[uid]
    if isinstance(data, (int, float)):
        # Migrate old flat format
        balances[uid] = {"wallet": int(data), "bank": 0}
        await _save_balances(guild_id, balances)
        data = balances[uid]
    return data


async def _set_balance(guild_id: int, user_id: int, wallet: int, bank: int) -> None:
    balances = await _get_all_balances(guild_id)
    balances[str(user_id)] = {
        "wallet": max(0, min(wallet, MAX_BALANCE)),
        "bank":   max(0, min(bank,   MAX_BALANCE)),
    }
    await _save_balances(guild_id, balances)


async def _get_store(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == ITEMS_RULE:
            return r.get("config") or {}
    return {}


async def _save_store(guild_id: int, store: dict) -> None:
    await db.upsert_automod_rule(ITEMS_RULE, True, store, guild_id)


async def _get_inventory(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == INVENTORY_RULE:
            return r.get("config") or {}
    return {}


async def _save_inventory(guild_id: int, inv: dict) -> None:
    await db.upsert_automod_rule(INVENTORY_RULE, True, inv, guild_id)


async def _get_cooldowns(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == COOLDOWN_RULE:
            return r.get("config") or {}
    return {}


async def _save_cooldowns(guild_id: int, cd: dict) -> None:
    await db.upsert_automod_rule(COOLDOWN_RULE, True, cd, guild_id)


async def _check_cooldown(guild_id: int, user_id: int, action: str, seconds: int) -> tuple[bool, int]:
    """Returns (can_use, seconds_remaining)."""
    cd    = await _get_cooldowns(guild_id)
    key   = f"{user_id}:{action}"
    last  = cd.get(key, 0)
    now   = time.time()
    diff  = now - last
    if diff < seconds:
        return False, int(seconds - diff)
    cd[key] = now
    await _save_cooldowns(guild_id, cd)
    return True, 0


async def _get_audit(guild_id: int) -> list:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == AUDIT_RULE:
            return r.get("config") or []
    return []


async def _add_audit(guild_id: int, user_id: int, action: str, amount: int, note: str = "") -> None:
    audit = await _get_audit(guild_id)
    audit.append({
        "user_id":   user_id,
        "action":    action,
        "amount":    amount,
        "note":      note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    # Keep last 200 entries
    if len(audit) > 200:
        audit = audit[-200:]
    await db.upsert_automod_rule(AUDIT_RULE, True, audit, guild_id)


async def _get_milestone_roles(guild_id: int) -> dict:
    """Returns {milestone_name: role_id} e.g. {"millionaire": 123456}"""
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == MILESTONE_RULE:
            return r.get("config") or {}
    return {}


async def _save_milestone_roles(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(MILESTONE_RULE, True, data, guild_id)


async def _check_and_award_milestones(
    guild: discord.Guild,
    member: discord.Member,
    new_total: int,
) -> list[str]:
    """
    Check if member crossed any milestone threshold and award the hardcoded role.
    Returns list of newly awarded milestone names.
    Adds a small delay between role assignments to avoid rate limits.
    """
    awarded = []
    member_role_ids = {r.id for r in member.roles}

    for threshold, name, role_id in MILESTONES:
        if new_total >= threshold and role_id not in member_role_ids:
            role = guild.get_role(role_id)
            if not role:
                continue
            try:
                await member.add_roles(role, reason=f"Economy milestone: {name}")
                awarded.append(name)
                await asyncio.sleep(0.5)  # avoid rate limiting on multiple awards
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                if e.status == 429:
                    await asyncio.sleep(2)  # back off on rate limit
                    try:
                        await member.add_roles(role, reason=f"Economy milestone: {name}")
                        awarded.append(name)
                    except Exception:
                        pass

    return awarded


def _cd_str(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def _fmt(cfg: dict, amount: int) -> str:
    sym  = cfg.get("currency_symbol", DEFAULT_CURRENCY)
    name = cfg.get("currency_name",   DEFAULT_CURRENCY_NAME)
    return f"{sym} **{amount:,}** {name}"


def _ok(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ECC71)

def _err(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xE74C3C)

def _econ(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"💰 {title}", description=desc, color=0xF1C40F)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class EconomyCog(commands.Cog, name="Economy"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession(headers={"User-Agent": "GlobalLeagueBot/1.0"})

    async def cog_unload(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()

    async def _maybe_award(
        self,
        interaction: discord.Interaction,
        new_wallet: int,
        bank: int,
    ) -> str:
        """Check milestones after any balance change. Returns extra text if roles awarded."""
        if not isinstance(interaction.user, discord.Member):
            return ""
        new_total = new_wallet + bank
        awarded   = await _check_and_award_milestones(interaction.guild, interaction.user, new_total)
        if not awarded:
            return ""
        return "\n" + "\n".join(f"🎉 You reached **{n.capitalize()}** status!" for n in awarded)

    # =====================================================================
    # BALANCE COMMANDS
    # =====================================================================

    @app_commands.command(name="balance", description="Check your wallet and bank balance.")
    @app_commands.describe(user="User to check (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def balance(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        target = user or interaction.user
        cfg    = await _get_config(interaction.guild.id)
        data   = await _get_balance(interaction.guild.id, target.id)
        wallet = data["wallet"]
        bank   = data["bank"]
        total  = wallet + bank
        sym    = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        name   = cfg.get("currency_name",   DEFAULT_CURRENCY_NAME)

        e = discord.Embed(title=f"💰 {target.display_name}'s Balance", color=0xF1C40F)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="👛 Wallet", value=f"{sym} {wallet:,}", inline=True)
        e.add_field(name="🏦 Bank",   value=f"{sym} {bank:,}",   inline=True)
        e.add_field(name="📊 Total",  value=f"{sym} {total:,}",  inline=True)
        e.set_footer(text=f"{name.capitalize()} • {interaction.guild.name}")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="money", description="Alias for /balance.")
    @app_commands.describe(user="User to check (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def money(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        await self.balance.callback(self, interaction, user)

    @app_commands.command(name="deposit", description="Deposit money from wallet into bank.")
    @app_commands.describe(amount="Amount to deposit, or 'all'")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def deposit(self, interaction: discord.Interaction, amount: str) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)
        wallet, bank = data["wallet"], data["bank"]

        amt = wallet if amount.lower() == "all" else int(amount) if amount.isdigit() else -1
        if amt <= 0 or amt > wallet:
            await interaction.response.send_message(
                embed=_err("Invalid Amount", f"You only have {_fmt(cfg, wallet)} in your wallet."), ephemeral=True
            )
            return

        await _set_balance(interaction.guild.id, interaction.user.id, wallet - amt, bank + amt)
        await _add_audit(interaction.guild.id, interaction.user.id, "deposit", amt)
        await interaction.response.send_message(
            embed=_econ("Deposited", f"Deposited {_fmt(cfg, amt)} into your bank.")
        )

    @app_commands.command(name="withdraw", description="Withdraw money from bank to wallet.")
    @app_commands.describe(amount="Amount to withdraw, or 'all'")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def withdraw(self, interaction: discord.Interaction, amount: str) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)
        wallet, bank = data["wallet"], data["bank"]

        amt = bank if amount.lower() == "all" else int(amount) if amount.isdigit() else -1
        if amt <= 0 or amt > bank:
            await interaction.response.send_message(
                embed=_err("Invalid Amount", f"You only have {_fmt(cfg, bank)} in your bank."), ephemeral=True
            )
            return

        await _set_balance(interaction.guild.id, interaction.user.id, wallet + amt, bank - amt)
        await _add_audit(interaction.guild.id, interaction.user.id, "withdraw", amt)
        await interaction.response.send_message(
            embed=_econ("Withdrawn", f"Withdrew {_fmt(cfg, amt)} to your wallet.")
        )

    @app_commands.command(name="give", description="Give money to another member.")
    @app_commands.describe(user="Who to give money to", amount="Amount to give")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=_err("Invalid", "You can't give money to yourself."), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(embed=_err("Invalid", "You can't give money to bots."), ephemeral=True)
            return

        cfg      = await _get_config(interaction.guild.id)
        giver    = await _get_balance(interaction.guild.id, interaction.user.id)
        receiver = await _get_balance(interaction.guild.id, user.id)

        if amount <= 0 or amount > giver["wallet"]:
            await interaction.response.send_message(
                embed=_err("Insufficient Funds", f"You only have {_fmt(cfg, giver['wallet'])} in your wallet."), ephemeral=True
            )
            return

        await _set_balance(interaction.guild.id, interaction.user.id, giver["wallet"] - amount, giver["bank"])
        await _set_balance(interaction.guild.id, user.id, receiver["wallet"] + amount, receiver["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "give", amount, f"to {user.id}")
        await interaction.response.send_message(
            embed=_econ("Money Sent", f"{interaction.user.mention} gave {_fmt(cfg, amount)} to {user.mention}.")
        )

    @app_commands.command(name="leaderboard", description="View the richest members in the server.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cfg      = await _get_config(interaction.guild.id)
        balances = await _get_all_balances(interaction.guild.id)
        sym      = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        # Sort by total (wallet + bank)
        sorted_users = sorted(
            balances.items(),
            key=lambda x: (x[1]["wallet"] + x[1]["bank"]) if isinstance(x[1], dict) else x[1],
            reverse=True,
        )[:10]

        e = discord.Embed(title="🏆 Economy Leaderboard", color=0xF1C40F)
        medals = ["🥇", "🥈", "🥉"]
        lines  = []
        for i, (uid, data) in enumerate(sorted_users):
            total  = (data["wallet"] + data["bank"]) if isinstance(data, dict) else data
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"User {uid}"
            lines.append(f"{medal} **{name}** — {sym} {total:,}")

        e.description = "\n".join(lines) if lines else "No data yet."
        e.set_footer(text=interaction.guild.name)
        await interaction.followup.send(embed=e)

    # =====================================================================
    # WORK COMMANDS
    # =====================================================================

    @app_commands.command(name="work", description="Work to earn money.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def work(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd_secs = int(cfg.get("cooldown_work", DEFAULT_COOLDOWNS["work"]))
        can_use, remaining = await _check_cooldown(interaction.guild.id, interaction.user.id, "work", cd_secs)

        if not can_use:
            await interaction.response.send_message(
                embed=_err("On Cooldown", f"You can work again in **{_cd_str(remaining)}**."), ephemeral=True
            )
            return

        pmin = int(cfg.get("work_min", DEFAULT_PAYOUTS["work_min"]))
        pmax = int(cfg.get("work_max", DEFAULT_PAYOUTS["work_max"]))
        earned = random.randint(pmin, pmax)

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + earned, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "work", earned)

        jobs = [
            "You delivered packages all day",
            "You coded for a startup",
            "You drove for a rideshare app",
            "You worked a shift at the café",
            "You freelanced as a designer",
            "You tutored students online",
            "You repaired phones at a kiosk",
        ]
        extra = await self._maybe_award(interaction, data["wallet"] + earned, data["bank"])
        await interaction.response.send_message(
            embed=_econ("Work Complete", f"{random.choice(jobs)} and earned {_fmt(cfg, earned)}!{extra}")
        )

    @app_commands.command(name="crime", description="Commit a crime for a chance at big money.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def crime(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd_secs = int(cfg.get("cooldown_crime", DEFAULT_COOLDOWNS["crime"]))
        can_use, remaining = await _check_cooldown(interaction.guild.id, interaction.user.id, "crime", cd_secs)

        if not can_use:
            await interaction.response.send_message(
                embed=_err("On Cooldown", f"You can commit a crime again in **{_cd_str(remaining)}**."), ephemeral=True
            )
            return

        fail_chance = float(cfg.get("crime_fail_chance", DEFAULT_PAYOUTS["crime_fail_chance"]))
        data        = await _get_balance(interaction.guild.id, interaction.user.id)

        if random.random() < fail_chance:
            fine = random.randint(
                int(cfg.get("crime_min", DEFAULT_PAYOUTS["crime_min"])) // 2,
                int(cfg.get("crime_min", DEFAULT_PAYOUTS["crime_min"])),
            )
            fine = min(fine, data["wallet"])
            await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] - fine, data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "crime_fail", -fine)
            crimes = ["You got caught shoplifting", "The heist went wrong", "You were identified on camera"]
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🚔 Busted!",
                    description=f"{random.choice(crimes)} and paid a fine of {_fmt(cfg, fine)}.",
                    color=0xE74C3C,
                )
            )
        else:
            earned = random.randint(
                int(cfg.get("crime_min", DEFAULT_PAYOUTS["crime_min"])),
                int(cfg.get("crime_max", DEFAULT_PAYOUTS["crime_max"])),
            )
            await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + earned, data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "crime", earned)
            crimes = ["You robbed a convenience store", "You ran a scam call center", "You hacked a small company"]
            extra = await self._maybe_award(interaction, data["wallet"] + earned, data["bank"])
            await interaction.response.send_message(
                embed=_econ("Crime Successful", f"{random.choice(crimes)} and got away with {_fmt(cfg, earned)}!{extra}")
            )

    @app_commands.command(name="rob", description="Attempt to rob another member's wallet.")
    @app_commands.describe(user="Who to rob")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def rob(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=_err("Invalid", "You can't rob yourself."), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(embed=_err("Invalid", "You can't rob a bot."), ephemeral=True)
            return

        cfg = await _get_config(interaction.guild.id)
        cd_secs = int(cfg.get("cooldown_rob", DEFAULT_COOLDOWNS["rob"]))
        can_use, remaining = await _check_cooldown(interaction.guild.id, interaction.user.id, "rob", cd_secs)
        if not can_use:
            await interaction.response.send_message(
                embed=_err("On Cooldown", f"You can rob again in **{_cd_str(remaining)}**."), ephemeral=True
            )
            return

        victim    = await _get_balance(interaction.guild.id, user.id)
        robber    = await _get_balance(interaction.guild.id, interaction.user.id)
        fail_chance = float(cfg.get("rob_fail_chance", DEFAULT_PAYOUTS["rob_fail_chance"]))

        if victim["wallet"] < 10:
            await interaction.response.send_message(
                embed=_err("Not Worth It", f"{user.mention} doesn't have enough in their wallet."), ephemeral=True
            )
            return

        if random.random() < fail_chance:
            fine = random.randint(50, 150)
            fine = min(fine, robber["wallet"])
            await _set_balance(interaction.guild.id, interaction.user.id, robber["wallet"] - fine, robber["bank"])
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🚔 Caught!",
                    description=f"You got caught trying to rob {user.mention} and paid a **{_fmt(cfg, fine)}** fine.",
                    color=0xE74C3C,
                )
            )
        else:
            stolen = random.randint(
                int(cfg.get("rob_min", DEFAULT_PAYOUTS["rob_min"])),
                min(int(cfg.get("rob_max", DEFAULT_PAYOUTS["rob_max"])), victim["wallet"]),
            )
            await _set_balance(interaction.guild.id, interaction.user.id, robber["wallet"] + stolen, robber["bank"])
            await _set_balance(interaction.guild.id, user.id, victim["wallet"] - stolen, victim["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "rob", stolen, f"from {user.id}")
            extra = await self._maybe_award(interaction, robber["wallet"] + stolen, robber["bank"])
            await interaction.response.send_message(
                embed=_econ("Robbery Successful", f"You stole {_fmt(cfg, stolen)} from {user.mention}!{extra}")
            )

    @app_commands.command(name="claim", description="Claim your daily reward.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def claim(self, interaction: discord.Interaction) -> None:
        cfg     = await _get_config(interaction.guild.id)
        cd_secs = int(cfg.get("cooldown_claim", DEFAULT_COOLDOWNS["claim"]))
        can_use, remaining = await _check_cooldown(interaction.guild.id, interaction.user.id, "claim", cd_secs)

        if not can_use:
            await interaction.response.send_message(
                embed=_err("Already Claimed", f"You can claim again in **{_cd_str(remaining)}**."), ephemeral=True
            )
            return

        amount = int(cfg.get("claim_amount", DEFAULT_PAYOUTS["claim_amount"]))
        data   = await _get_balance(interaction.guild.id, interaction.user.id)
        new_wallet = min(data["wallet"] + amount, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, new_wallet, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "claim", amount)

        desc = f"You claimed your daily {_fmt(cfg, amount)}!"

        # Check and award milestone roles
        if isinstance(interaction.user, discord.Member):
            new_total = new_wallet + data["bank"]
            awarded = await _check_and_award_milestones(interaction.guild, interaction.user, new_total)
            for name in awarded:
                desc += f"\n🎉 You reached **{name.capitalize()}** status!"

        await interaction.response.send_message(embed=_econ("Daily Claimed!", desc))

    # =====================================================================
    # STORE & INVENTORY
    # =====================================================================

    @app_commands.command(name="store", description="View the item store.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def store(self, interaction: discord.Interaction) -> None:
        cfg   = await _get_config(interaction.guild.id)
        items = await _get_store(interaction.guild.id)
        sym   = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        e = discord.Embed(title="🏪 Item Store", color=0x3498DB)
        if not items:
            e.description = "The store is empty. Admins can add items with `/add_store_item`."
        else:
            for item_id, item in items.items():
                e.add_field(
                    name=f"{item.get('emoji', '📦')} {item['name']} — {sym} {item['price']:,}",
                    value=item.get("description", "No description.") + f"\n`ID: {item_id}`",
                    inline=False,
                )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="buy", description="Buy an item from the store.")
    @app_commands.describe(item_id="Item ID from /store")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def buy(self, interaction: discord.Interaction, item_id: str) -> None:
        cfg   = await _get_config(interaction.guild.id)
        items = await _get_store(interaction.guild.id)

        if item_id not in items:
            await interaction.response.send_message(embed=_err("Not Found", f"Item `{item_id}` not found in store."), ephemeral=True)
            return

        item  = items[item_id]
        price = item["price"]
        data  = await _get_balance(interaction.guild.id, interaction.user.id)

        if data["wallet"] < price:
            await interaction.response.send_message(
                embed=_err("Insufficient Funds", f"You need {_fmt(cfg, price)} but only have {_fmt(cfg, data['wallet'])} in wallet."),
                ephemeral=True,
            )
            return

        # Add to inventory
        inv = await _get_inventory(interaction.guild.id)
        uid = str(interaction.user.id)
        if uid not in inv:
            inv[uid] = {}
        inv[uid][item_id] = inv[uid].get(item_id, 0) + 1
        await _save_inventory(interaction.guild.id, inv)

        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] - price, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "buy", -price, item_id)

        await interaction.response.send_message(
            embed=_econ("Purchased!", f"You bought **{item['name']}** for {_fmt(cfg, price)}.")
        )

    @app_commands.command(name="sell", description="Sell an item back for half its price.")
    @app_commands.describe(item_id="Item ID to sell")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def sell(self, interaction: discord.Interaction, item_id: str) -> None:
        cfg   = await _get_config(interaction.guild.id)
        items = await _get_store(interaction.guild.id)
        inv   = await _get_inventory(interaction.guild.id)
        uid   = str(interaction.user.id)

        if item_id not in items:
            await interaction.response.send_message(embed=_err("Not Found", f"Item `{item_id}` doesn't exist."), ephemeral=True)
            return
        if uid not in inv or inv[uid].get(item_id, 0) < 1:
            await interaction.response.send_message(embed=_err("Not Owned", "You don't own that item."), ephemeral=True)
            return

        sell_price = items[item_id]["price"] // 2
        inv[uid][item_id] -= 1
        if inv[uid][item_id] <= 0:
            del inv[uid][item_id]
        await _save_inventory(interaction.guild.id, inv)

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + sell_price, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "sell", sell_price, item_id)

        await interaction.response.send_message(
            embed=_econ("Sold!", f"Sold **{items[item_id]['name']}** for {_fmt(cfg, sell_price)}.")
        )

    @app_commands.command(name="inventory", description="View your item inventory.")
    @app_commands.describe(user="User to view (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def inventory(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        target = user or interaction.user
        items  = await _get_store(interaction.guild.id)
        inv    = await _get_inventory(interaction.guild.id)
        uid    = str(target.id)

        e = discord.Embed(title=f"🎒 {target.display_name}'s Inventory", color=0x9B59B6)
        e.set_thumbnail(url=target.display_avatar.url)

        user_inv = inv.get(uid, {})
        if not user_inv:
            e.description = "No items in inventory."
        else:
            for iid, qty in user_inv.items():
                item = items.get(iid, {})
                name = item.get("name", iid)
                emoji = item.get("emoji", "📦")
                e.add_field(name=f"{emoji} {name}", value=f"Qty: **{qty}**\n`ID: {iid}`", inline=True)

        await interaction.response.send_message(embed=e)

    @app_commands.command(name="use_item", description="Use an item from your inventory.")
    @app_commands.describe(item_id="Item ID to use")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def use_item(self, interaction: discord.Interaction, item_id: str) -> None:
        items = await _get_store(interaction.guild.id)
        inv   = await _get_inventory(interaction.guild.id)
        uid   = str(interaction.user.id)

        if item_id not in items:
            await interaction.response.send_message(embed=_err("Not Found", f"Item `{item_id}` doesn't exist."), ephemeral=True)
            return
        if uid not in inv or inv[uid].get(item_id, 0) < 1:
            await interaction.response.send_message(embed=_err("Not Owned", "You don't own that item."), ephemeral=True)
            return

        item = items[item_id]
        use_msg = item.get("use_message", f"You used **{item['name']}**.")

        # Consume item
        inv[uid][item_id] -= 1
        if inv[uid][item_id] <= 0:
            del inv[uid][item_id]
        await _save_inventory(interaction.guild.id, inv)

        # Apply role reward if configured
        role_id = item.get("gives_role_id")
        if role_id and isinstance(interaction.user, discord.Member):
            role = interaction.guild.get_role(int(role_id))
            if role:
                try:
                    await interaction.user.add_roles(role, reason="Economy item used")
                    use_msg += f"\nYou received the {role.mention} role!"
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            embed=discord.Embed(title=f"{item.get('emoji','📦')} Item Used", description=use_msg, color=0x2ECC71)
        )

    # =====================================================================
    # GAMBLING
    # =====================================================================

    @app_commands.command(name="blackjack", description="Play a game of blackjack.")
    @app_commands.describe(bet="Amount to bet")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def blackjack(self, interaction: discord.Interaction, bet: int) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in your wallet."), ephemeral=True
            )
            return

        def card_value(card: str) -> int:
            rank = card.split()[0]
            if rank in ("J", "Q", "K"):
                return 10
            if rank == "A":
                return 11
            return int(rank)

        def hand_total(hand: list) -> int:
            total = sum(card_value(c) for c in hand)
            aces  = sum(1 for c in hand if c.startswith("A"))
            while total > 21 and aces:
                total -= 10
                aces  -= 1
            return total

        def new_deck():
            suits = ["♠️", "♥️", "♦️", "♣️"]
            ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
            deck  = [f"{r} {s}" for r in ranks for s in suits]
            random.shuffle(deck)
            return deck

        deck   = new_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        def hand_str(hand, hide_second=False) -> str:
            if hide_second:
                return f"{hand[0]}, 🂠"
            return ", ".join(hand)

        # Natural blackjack check
        if hand_total(player) == 21:
            winnings = int(bet * 1.5)
            await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + winnings, data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "blackjack_win", winnings)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🃏 Blackjack! Natural 21!",
                    description=(
                        f"Your hand: {hand_str(player)} = **21**\n"
                        f"You win {_fmt(cfg, winnings)}!"
                    ),
                    color=0xF1C40F,
                )
            )
            return

        view = BlackjackView(
            cog=self, interaction=interaction, bet=bet,
            player=player, dealer=dealer, deck=deck, cfg=cfg, data=data,
        )
        e = discord.Embed(title="🃏 Blackjack", color=0x2ECC71)
        e.add_field(name=f"Your Hand ({hand_total(player)})", value=hand_str(player), inline=True)
        e.add_field(name="Dealer Hand", value=hand_str(dealer, hide_second=True), inline=True)
        e.set_footer(text=f"Bet: {bet:,}")
        await interaction.response.send_message(embed=e, view=view)

    @app_commands.command(name="slots", description="Spin the slot machine.")
    @app_commands.describe(bet="Amount to bet")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def slots(self, interaction: discord.Interaction, bet: int) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in your wallet."), ephemeral=True
            )
            return

        symbols   = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
        weights   = [30, 25, 20, 15, 6, 3, 1]
        result    = random.choices(symbols, weights=weights, k=3)
        s1, s2, s3 = result

        if s1 == s2 == s3:
            if s3 == "7️⃣":
                mult, msg = 20, "🎰 **JACKPOT! TRIPLE 7s!!**"
            elif s3 == "💎":
                mult, msg = 10, "💎 **Triple Diamonds!**"
            elif s3 == "⭐":
                mult, msg = 5, "⭐ **Triple Stars!**"
            else:
                mult, msg = 3, "🎉 **Three of a Kind!**"
        elif s1 == s2 or s2 == s3 or s1 == s3:
            mult, msg = 1.5, "✨ **Two of a Kind!**"
        else:
            mult, msg = 0, "❌ No match."

        net = int(bet * mult) - bet
        new_wallet = data["wallet"] + net
        await _set_balance(interaction.guild.id, interaction.user.id, new_wallet, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "slots", net)

        color  = 0xF1C40F if net > 0 else (0xE74C3C if net < 0 else 0x95A5A6)
        result_line = "Won" if net > 0 else ("Lost" if net < 0 else "Broke Even")
        e = discord.Embed(title="🎰 Slot Machine", color=color)
        e.description = f"[ {s1} | {s2} | {s3} ]\n\n{msg}"
        e.add_field(name=result_line, value=_fmt(cfg, abs(net)), inline=True)
        e.add_field(name="New Balance", value=_fmt(cfg, new_wallet), inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="roulette", description="Bet on red, black, or a number (0-36).")
    @app_commands.describe(bet="Amount to bet", choice="red, black, green, or a number 0-36")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def roulette(self, interaction: discord.Interaction, bet: int, choice: str) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return

        spin    = random.randint(0, 36)
        reds    = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        is_red  = spin in reds
        color_s = "🔴 Red" if is_red else ("🟢 Green" if spin == 0 else "⚫ Black")

        choice_l = choice.lower().strip()
        if choice_l in ("red", "🔴"):
            win = is_red
            mult = 2
        elif choice_l in ("black", "⚫"):
            win = not is_red and spin != 0
            mult = 2
        elif choice_l in ("green", "0"):
            win = spin == 0
            mult = 14
        elif choice_l.isdigit() and 0 <= int(choice_l) <= 36:
            win  = spin == int(choice_l)
            mult = 36
        else:
            await interaction.response.send_message(
                embed=_err("Invalid Choice", "Choose `red`, `black`, `green`, or a number `0-36`."), ephemeral=True
            )
            return

        net = bet * (mult - 1) if win else -bet
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + net, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "roulette", net)

        e = discord.Embed(
            title="🎡 Roulette",
            description=f"The ball landed on **{spin}** ({color_s})",
            color=0xF1C40F if win else 0xE74C3C,
        )
        e.add_field(name="Your Bet", value=f"{choice} — {_fmt(cfg, bet)}", inline=True)
        e.add_field(name="Result",   value=f"{'Won' if win else 'Lost'} {_fmt(cfg, abs(net))}", inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="fight", description="Enter your rooster in a fight for money.")
    @app_commands.describe(bet="Amount to bet")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def fight(self, interaction: discord.Interaction, bet: int) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return

        roosters  = ["Big Red", "Thunder Cluck", "Iron Beak", "Golden Spurs", "Shadow Wing"]
        yours     = random.choice(roosters)
        opponent  = random.choice([r for r in roosters if r != yours])
        win       = random.random() > 0.45

        net = bet if win else -bet
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + net, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "fight", net)

        e = discord.Embed(
            title="🐓 Rooster Fight",
            description=(
                f"**{yours}** vs **{opponent}**\n\n"
                + (f"🏆 **{yours} wins!** You earned {_fmt(cfg, bet)}!" if win
                   else f"💀 **{opponent} wins!** You lost {_fmt(cfg, bet)}.")
            ),
            color=0xF1C40F if win else 0xE74C3C,
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="roll", description="Roll dice and bet on the outcome.")
    @app_commands.describe(bet="Amount to bet", guess="Guess high (7+) or low (6-) or exact number 1-12")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def roll(self, interaction: discord.Interaction, bet: int, guess: str) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return

        d1, d2  = random.randint(1, 6), random.randint(1, 6)
        total   = d1 + d2
        guess_l = guess.lower().strip()

        if guess_l == "high":
            win, mult = total >= 7, 2
        elif guess_l == "low":
            win, mult = total <= 6, 2
        elif guess_l.isdigit() and 2 <= int(guess_l) <= 12:
            win, mult = total == int(guess_l), 5
        else:
            await interaction.response.send_message(
                embed=_err("Invalid Guess", "Choose `high`, `low`, or a number `2-12`."), ephemeral=True
            )
            return

        net = bet * (mult - 1) if win else -bet
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + net, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "roll", net)

        e = discord.Embed(
            title="🎲 Dice Roll",
            description=f"🎲 {d1}  +  🎲 {d2}  =  **{total}**",
            color=0xF1C40F if win else 0xE74C3C,
        )
        e.add_field(name="Result", value=f"{'Won' if win else 'Lost'} {_fmt(cfg, abs(net))}", inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="pick", description="Pick a number 1-10 and win if you guess right.")
    @app_commands.describe(bet="Amount to bet", number="Number to pick (1-10)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def pick(self, interaction: discord.Interaction, bet: int, number: int) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return
        if not 1 <= number <= 10:
            await interaction.response.send_message(embed=_err("Invalid", "Pick a number between 1 and 10."), ephemeral=True)
            return

        result = random.randint(1, 10)
        win    = result == number
        net    = bet * 8 if win else -bet

        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] + net, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "pick", net)

        e = discord.Embed(
            title="🔢 Pick a Number",
            description=(
                f"You picked **{number}**, the number was **{result}**.\n"
                + (f"🎉 Correct! You won {_fmt(cfg, net)}!" if win else f"❌ Wrong! You lost {_fmt(cfg, bet)}.")
            ),
            color=0xF1C40F if win else 0xE74C3C,
        )
        await interaction.response.send_message(embed=e)

    # =====================================================================
    # ADMIN COMMANDS
    # =====================================================================

    @app_commands.command(name="add_money", description="[Admin] Add money to a user's wallet.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def add_money(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, user.id)
        await _set_balance(interaction.guild.id, user.id, data["wallet"] + amount, data["bank"])
        await _add_audit(interaction.guild.id, user.id, "admin_add", amount, str(interaction.user.id))
        await interaction.response.send_message(
            embed=_ok("Money Added", f"Added {_fmt(cfg, amount)} to {user.mention}."), ephemeral=True
        )

    @app_commands.command(name="remove_money", description="[Admin] Remove money from a user.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def remove_money(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, user.id)
        await _set_balance(interaction.guild.id, user.id, max(0, data["wallet"] - amount), data["bank"])
        await _add_audit(interaction.guild.id, user.id, "admin_remove", -amount, str(interaction.user.id))
        await interaction.response.send_message(
            embed=_ok("Money Removed", f"Removed {_fmt(cfg, amount)} from {user.mention}."), ephemeral=True
        )

    @app_commands.command(name="set_money", description="[Admin] Set a user's wallet to an exact amount.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def set_money(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, user.id)
        await _set_balance(interaction.guild.id, user.id, amount, data["bank"])
        await _add_audit(interaction.guild.id, user.id, "admin_set", amount, str(interaction.user.id))
        await interaction.response.send_message(
            embed=_ok("Balance Set", f"Set {user.mention}'s wallet to {_fmt(cfg, amount)}."), ephemeral=True
        )

    @app_commands.command(name="reset_economy", description="[Admin] Wipe ALL economy data. Irreversible.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def reset_economy(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await db.upsert_automod_rule(BALANCE_RULE,   True, {}, interaction.guild.id)
        await db.upsert_automod_rule(COOLDOWN_RULE,  True, {}, interaction.guild.id)
        await db.upsert_automod_rule(INVENTORY_RULE, True, {}, interaction.guild.id)
        await db.upsert_automod_rule(AUDIT_RULE,     True, [], interaction.guild.id)
        await interaction.response.send_message(
            embed=_ok("Economy Reset", "All balances, cooldowns, and inventories have been wiped."), ephemeral=True
        )

    @app_commands.command(name="add_store_item", description="[Admin] Add an item to the store.")
    @app_commands.describe(
        item_id="Unique ID for this item (no spaces)",
        name="Display name",
        price="Price in currency",
        description="Item description",
        emoji="Emoji for the item",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def add_store_item(
        self, interaction: discord.Interaction,
        item_id: str, name: str, price: int,
        description: str = "No description.",
        emoji: str = "📦",
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        store = await _get_store(interaction.guild.id)
        store[item_id] = {"name": name, "price": price, "description": description, "emoji": emoji}
        await _save_store(interaction.guild.id, store)
        await interaction.response.send_message(
            embed=_ok("Item Added", f"**{emoji} {name}** added to store at {price:,} coins."), ephemeral=True
        )

    @app_commands.command(name="remove_store_item", description="[Admin] Remove an item from the store.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def remove_store_item(self, interaction: discord.Interaction, item_id: str) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        store = await _get_store(interaction.guild.id)
        if item_id not in store:
            await interaction.response.send_message(embed=_err("Not Found", f"Item `{item_id}` not found."), ephemeral=True)
            return
        removed = store.pop(item_id)
        await _save_store(interaction.guild.id, store)
        await interaction.response.send_message(
            embed=_ok("Item Removed", f"**{removed['name']}** removed from store."), ephemeral=True
        )

    @app_commands.command(name="edit_store_item", description="[Admin] Edit an existing store item.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def edit_store_item(
        self, interaction: discord.Interaction,
        item_id: str,
        name: Optional[str] = None,
        price: Optional[int] = None,
        description: Optional[str] = None,
        emoji: Optional[str] = None,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        store = await _get_store(interaction.guild.id)
        if item_id not in store:
            await interaction.response.send_message(embed=_err("Not Found", f"Item `{item_id}` not found."), ephemeral=True)
            return
        if name:        store[item_id]["name"]        = name
        if price:       store[item_id]["price"]       = price
        if description: store[item_id]["description"] = description
        if emoji:       store[item_id]["emoji"]       = emoji
        await _save_store(interaction.guild.id, store)
        await interaction.response.send_message(
            embed=_ok("Item Updated", f"**{store[item_id]['name']}** has been updated."), ephemeral=True
        )

    @app_commands.command(name="set_currency", description="[Admin] Set the currency symbol and name.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def set_currency(self, interaction: discord.Interaction, symbol: str, name: str) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await _save_config(interaction.guild.id, {"currency_symbol": symbol, "currency_name": name})
        await interaction.response.send_message(
            embed=_ok("Currency Updated", f"Currency is now **{symbol} {name}**."), ephemeral=True
        )

    @app_commands.command(name="set_start_balance", description="[Admin] Set starting balance for new users.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def set_start_balance(self, interaction: discord.Interaction, amount: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await _save_config(interaction.guild.id, {"start_balance": amount})
        await interaction.response.send_message(
            embed=_ok("Start Balance Set", f"New users start with **{amount:,}** coins."), ephemeral=True
        )

    @app_commands.command(name="set_cooldown", description="[Admin] Set cooldown for a command in seconds.")
    @app_commands.choices(command=[
        app_commands.Choice(name="work",  value="cooldown_work"),
        app_commands.Choice(name="crime", value="cooldown_crime"),
        app_commands.Choice(name="rob",   value="cooldown_rob"),
        app_commands.Choice(name="claim", value="cooldown_claim"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def set_cooldown(self, interaction: discord.Interaction, command: str, seconds: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await _save_config(interaction.guild.id, {command: seconds})
        cmd_name = command.replace("cooldown_", "")
        await interaction.response.send_message(
            embed=_ok("Cooldown Set", f"`/{cmd_name}` cooldown set to **{_cd_str(seconds)}**."), ephemeral=True
        )

    @app_commands.command(name="set_payout", description="[Admin] Set min/max payout for work or crime.")
    @app_commands.choices(command=[
        app_commands.Choice(name="work min",  value="work_min"),
        app_commands.Choice(name="work max",  value="work_max"),
        app_commands.Choice(name="crime min", value="crime_min"),
        app_commands.Choice(name="crime max", value="crime_max"),
        app_commands.Choice(name="claim amount", value="claim_amount"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def set_payout(self, interaction: discord.Interaction, command: str, amount: int) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await _save_config(interaction.guild.id, {command: amount})
        await interaction.response.send_message(
            embed=_ok("Payout Updated", f"`{command}` set to **{amount:,}**."), ephemeral=True
        )

    @app_commands.command(name="economy_stats", description="View economy-wide statistics.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def economy_stats(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        cfg      = await _get_config(interaction.guild.id)
        balances = await _get_all_balances(interaction.guild.id)
        sym      = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        total_users  = len(balances)
        total_wallet = sum(v["wallet"] for v in balances.values() if isinstance(v, dict))
        total_bank   = sum(v["bank"]   for v in balances.values() if isinstance(v, dict))
        total_money  = total_wallet + total_bank
        store_items  = len(await _get_store(interaction.guild.id))
        audit        = await _get_audit(interaction.guild.id)

        e = discord.Embed(title="📊 Economy Statistics", color=0xF1C40F)
        e.add_field(name="👥 Total Users",    value=f"{total_users:,}",       inline=True)
        e.add_field(name="💰 Total in Circulation", value=f"{sym} {total_money:,}", inline=True)
        e.add_field(name="👛 In Wallets",     value=f"{sym} {total_wallet:,}", inline=True)
        e.add_field(name="🏦 In Banks",       value=f"{sym} {total_bank:,}",  inline=True)
        e.add_field(name="🏪 Store Items",    value=f"{store_items}",         inline=True)
        e.add_field(name="📋 Audit Entries",  value=f"{len(audit)}",          inline=True)
        e.add_field(name="🪙 Currency",       value=f"{sym} {cfg.get('currency_name', DEFAULT_CURRENCY_NAME)}", inline=True)
        e.add_field(name="🆕 Start Balance",  value=f"{sym} {cfg.get('start_balance', DEFAULT_START_BAL):,}",  inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="money_audit_log", description="[Admin] View recent economy transactions.")
    @app_commands.describe(user="Filter by user (optional)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def money_audit_log(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        cfg   = await _get_config(interaction.guild.id)
        audit = await _get_audit(interaction.guild.id)
        sym   = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        if user:
            audit = [a for a in audit if a.get("user_id") == user.id]

        audit = list(reversed(audit))[:15]

        e = discord.Embed(
            title=f"📋 Audit Log{f' — {user}' if user else ''}",
            color=0x95A5A6,
        )
        if not audit:
            e.description = "No entries found."
        else:
            lines = []
            for entry in audit:
                ts   = entry.get("timestamp", "")[:10]
                uid  = entry.get("user_id")
                act  = entry.get("action", "?")
                amt  = entry.get("amount", 0)
                sign = "+" if amt >= 0 else ""
                lines.append(f"`{ts}` <@{uid}> **{act}** {sign}{sym}{amt:,}")
            e.description = "\n".join(lines)

        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("EconomyCog error: %s", error)
        msg = "❌ Something went wrong. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Blackjack View
# ---------------------------------------------------------------------------

class BlackjackView(discord.ui.View):
    def __init__(self, *, cog, interaction, bet, player, dealer, deck, cfg, data):
        super().__init__(timeout=60)
        self.cog         = cog
        self.interaction = interaction
        self.bet         = bet
        self.player      = player
        self.dealer      = dealer
        self.deck        = deck
        self.cfg         = cfg
        self.data        = data

    def _total(self, hand):
        def cv(c):
            r = c.split()[0]
            if r in ("J","Q","K"): return 10
            if r == "A": return 11
            return int(r)
        total = sum(cv(c) for c in hand)
        aces  = sum(1 for c in hand if c.startswith("A"))
        while total > 21 and aces:
            total -= 10; aces -= 1
        return total

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return

        self.player.append(self.deck.pop())
        pt = self._total(self.player)

        if pt > 21:
            await _set_balance(interaction.guild.id, interaction.user.id, self.data["wallet"] - self.bet, self.data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "blackjack_loss", -self.bet)
            e = discord.Embed(title="🃏 Bust!", description=f"Your hand: {', '.join(self.player)} = **{pt}**\nYou lost {_fmt(self.cfg, self.bet)}.", color=0xE74C3C)
            await interaction.response.edit_message(embed=e, view=None)
            self.stop()
        else:
            e = discord.Embed(title="🃏 Blackjack", color=0x2ECC71)
            e.add_field(name=f"Your Hand ({pt})", value=", ".join(self.player), inline=True)
            e.add_field(name="Dealer Hand", value=f"{self.dealer[0]}, 🂠", inline=True)
            e.set_footer(text=f"Bet: {self.bet:,}")
            await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return

        # Dealer plays
        while self._total(self.dealer) < 17:
            self.dealer.append(self.deck.pop())

        pt, dt = self._total(self.player), self._total(self.dealer)

        if dt > 21 or pt > dt:
            net = self.bet
            result = f"🎉 You win! Dealer busted." if dt > 21 else f"🎉 You win! {pt} vs {dt}."
            color  = 0xF1C40F
        elif pt == dt:
            net = 0
            result = f"🤝 Push! Both have {pt}."
            color  = 0x95A5A6
        else:
            net = -self.bet
            result = f"❌ Dealer wins. {dt} vs {pt}."
            color  = 0xE74C3C

        new_w = self.data["wallet"] + net
        await _set_balance(interaction.guild.id, interaction.user.id, new_w, self.data["bank"])
        if net != 0:
            await _add_audit(interaction.guild.id, interaction.user.id,
                             "blackjack_win" if net > 0 else "blackjack_loss", net)

        e = discord.Embed(title="🃏 Blackjack — Result", description=result, color=color)
        e.add_field(name=f"Your Hand ({pt})", value=", ".join(self.player),  inline=True)
        e.add_field(name=f"Dealer Hand ({dt})", value=", ".join(self.dealer), inline=True)
        if net != 0:
            e.add_field(name="Net", value=_fmt(self.cfg, abs(net)), inline=True)
        await interaction.response.edit_message(embed=e, view=None)
        self.stop()



# ---------------------------------------------------------------------------
# Extra Economy — Constants & Stock Helpers
# ---------------------------------------------------------------------------
STOCKS_RULE    = "economy_stocks"
PORTFOLIO_RULE = "economy_portfolio"

# ── Default cooldowns ────────────────────────────────────────────────────
CD = {
    "fish":  1800,   # 30 min
    "hunt":  2700,   # 45 min
    "mine":  3600,   # 1 hour
    "chop":  2700,   # 45 min
    "beg":   300,    # 5 min
}

# ── Stock list ────────────────────────────────────────────────────────────
# Fictional stocks, prices fluctuate every time someone checks
BASE_STOCKS = {
    "ELURA": {"name": "Elura Corp",       "price": 150,    "volatility": 0.08},
    "GLDCN": {"name": "GoldCoin Inc",     "price": 2200,   "volatility": 0.12},
    "NXGEN": {"name": "NextGen Tech",     "price": 450,    "volatility": 0.15},
    "BRKR":  {"name": "Broker Financial", "price": 800,    "volatility": 0.06},
    "MOON":  {"name": "MoonShot Ventures","price": 50,     "volatility": 0.25},
    "VAULT": {"name": "Vault Banking",    "price": 1200,   "volatility": 0.05},
    "APEX":  {"name": "Apex Industries",  "price": 320,    "volatility": 0.10},
    "ZCOIN": {"name": "ZCoin Exchange",   "price": 75,     "volatility": 0.20},
}


# ---------------------------------------------------------------------------
# Stock DB helpers
# ---------------------------------------------------------------------------

async def _get_stock_prices(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == STOCKS_RULE:
            return r.get("config") or {}
    # Seed initial prices
    prices = {k: {"price": v["price"], "last_update": 0} for k, v in BASE_STOCKS.items()}
    await db.upsert_automod_rule(STOCKS_RULE, True, prices, guild_id)
    return prices


async def _get_portfolio(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == PORTFOLIO_RULE:
            return r.get("config") or {}
    return {}


async def _save_portfolio(guild_id: int, data: dict) -> None:
    await db.upsert_automod_rule(PORTFOLIO_RULE, True, data, guild_id)


def _fluctuate_price(current: int, volatility: float) -> int:
    """Randomly move price up or down based on volatility."""
    change = random.uniform(-volatility, volatility)
    new    = max(1, int(current * (1 + change)))
    return new


async def _get_live_prices(guild_id: int) -> dict:
    """Return current prices, fluctuating each call."""
    prices = await _get_stock_prices(guild_id)
    now    = time.time()
    updated = False

    for ticker, data in prices.items():
        # Fluctuate if last update was > 5 minutes ago
        if now - data.get("last_update", 0) > 300:
            vol = BASE_STOCKS.get(ticker, {}).get("volatility", 0.10)
            data["price"]       = _fluctuate_price(data["price"], vol)
            data["last_update"] = now
            updated = True

    if updated:
        await db.upsert_automod_rule(STOCKS_RULE, True, prices, guild_id)

    return prices
class EconomyExtraCog(commands.Cog, name="EconomyExtra"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession(headers={"User-Agent": "GlobalLeagueBot/1.0"})

    async def cog_unload(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()

    async def _maybe_award(self, interaction, new_wallet, bank) -> str:
        if not isinstance(interaction.user, discord.Member):
            return ""
        awarded = await _check_and_award_milestones(interaction.guild, interaction.user, new_wallet + bank)
        if not awarded:
            return ""
        return "\n" + "\n".join(f"🎉 You reached **{n.capitalize()}** status!" for n in awarded)

    # =====================================================================
    # ACTIVITY COMMANDS
    # =====================================================================

    @app_commands.command(name="fish", description="Go fishing for coins.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def fish(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd  = int(cfg.get("cooldown_fish", CD["fish"]))
        ok, rem = await _check_cooldown(interaction.guild.id, interaction.user.id, "fish", cd)
        if not ok:
            await interaction.response.send_message(embed=_err("On Cooldown", f"You can fish again in **{_cd_str(rem)}**."), ephemeral=True)
            return

        catches = [
            ("🐟 Common Fish",    random.randint(20,  60),   0.40),
            ("🐠 Tropical Fish",  random.randint(60,  120),  0.25),
            ("🐡 Pufferfish",     random.randint(40,  90),   0.15),
            ("🦞 Lobster",        random.randint(150, 280),  0.10),
            ("🦈 Shark",          random.randint(300, 500),  0.06),
            ("💎 Diamond Fish",   random.randint(800, 1500), 0.03),
            ("🎣 Old Boot",       random.randint(1,   5),    0.01),
        ]
        r     = random.random()
        cumul = 0
        name, earned = "🐟 Common Fish", 30
        for n, amt, chance in catches:
            cumul += chance
            if r <= cumul:
                name, earned = n, amt
                break

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + earned, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "fish", earned)
        extra = await self._maybe_award(interaction, nw, data["bank"])

        e = discord.Embed(title="🎣 Fishing", color=0x3498DB)
        e.description = f"You caught a **{name}** and sold it for {_fmt(cfg, earned)}!{extra}"
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="hunt", description="Go hunting for coins.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def hunt(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd  = int(cfg.get("cooldown_hunt", CD["hunt"]))
        ok, rem = await _check_cooldown(interaction.guild.id, interaction.user.id, "hunt", cd)
        if not ok:
            await interaction.response.send_message(embed=_err("On Cooldown", f"You can hunt again in **{_cd_str(rem)}**."), ephemeral=True)
            return

        animals = [
            ("🐇 Rabbit",   random.randint(30,  70),   0.35),
            ("🦊 Fox",      random.randint(80,  150),  0.25),
            ("🦌 Deer",     random.randint(150, 280),  0.18),
            ("🐗 Boar",     random.randint(200, 350),  0.12),
            ("🐻 Bear",     random.randint(350, 600),  0.07),
            ("🦁 Lion",     random.randint(600, 1000), 0.02),
            ("🐉 Dragon",   random.randint(1500, 3000),0.01),
        ]
        r     = random.random()
        cumul = 0
        name, earned = "🐇 Rabbit", 40
        for n, amt, chance in animals:
            cumul += chance
            if r <= cumul:
                name, earned = n, amt
                break

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + earned, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "hunt", earned)
        extra = await self._maybe_award(interaction, nw, data["bank"])

        e = discord.Embed(title="🏹 Hunting", color=0x8B4513)
        e.description = f"You hunted a **{name}** and earned {_fmt(cfg, earned)}!{extra}"
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="mine", description="Mine for coins and gems.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def mine(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd  = int(cfg.get("cooldown_mine", CD["mine"]))
        ok, rem = await _check_cooldown(interaction.guild.id, interaction.user.id, "mine", cd)
        if not ok:
            await interaction.response.send_message(embed=_err("On Cooldown", f"You can mine again in **{_cd_str(rem)}**."), ephemeral=True)
            return

        finds = [
            ("⛏️ Coal",      random.randint(20,  50),   0.35),
            ("🪨 Iron Ore",  random.randint(50,  100),  0.25),
            ("🥇 Gold",      random.randint(100, 250),  0.18),
            ("💎 Diamond",   random.randint(300, 600),  0.12),
            ("🔮 Amethyst",  random.randint(400, 700),  0.07),
            ("🌟 Starstone", random.randint(800, 1500), 0.02),
            ("👑 Crown Gem", random.randint(2000, 4000),0.01),
        ]
        r     = random.random()
        cumul = 0
        name, earned = "⛏️ Coal", 25
        for n, amt, chance in finds:
            cumul += chance
            if r <= cumul:
                name, earned = n, amt
                break

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + earned, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "mine", earned)
        extra = await self._maybe_award(interaction, nw, data["bank"])

        e = discord.Embed(title="⛏️ Mining", color=0x7F8C8D)
        e.description = f"You mined **{name}** and sold it for {_fmt(cfg, earned)}!{extra}"
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="chop", description="Chop wood for coins.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def chop(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd  = int(cfg.get("cooldown_chop", CD["chop"]))
        ok, rem = await _check_cooldown(interaction.guild.id, interaction.user.id, "chop", cd)
        if not ok:
            await interaction.response.send_message(embed=_err("On Cooldown", f"You can chop again in **{_cd_str(rem)}**."), ephemeral=True)
            return

        logs = [
            ("🪵 Oak Wood",      random.randint(25,  60),   0.35),
            ("🌲 Pine Wood",     random.randint(50,  100),  0.25),
            ("🍂 Maple Wood",    random.randint(80,  160),  0.20),
            ("🪵 Ebony Wood",    random.randint(200, 350),  0.12),
            ("✨ Enchanted Log", random.randint(400, 700),  0.06),
            ("🌟 Ancient Wood",  random.randint(800, 1400), 0.02),
        ]
        r     = random.random()
        cumul = 0
        name, earned = "🪵 Oak Wood", 30
        for n, amt, chance in logs:
            cumul += chance
            if r <= cumul:
                name, earned = n, amt
                break

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + earned, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "chop", earned)
        extra = await self._maybe_award(interaction, nw, data["bank"])

        e = discord.Embed(title="🪓 Chopping", color=0x27AE60)
        e.description = f"You chopped **{name}** and sold it for {_fmt(cfg, earned)}!{extra}"
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="beg", description="Beg for coins. Humiliating but effective.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def beg(self, interaction: discord.Interaction) -> None:
        cfg = await _get_config(interaction.guild.id)
        cd  = int(cfg.get("cooldown_beg", CD["beg"]))
        ok, rem = await _check_cooldown(interaction.guild.id, interaction.user.id, "beg", cd)
        if not ok:
            await interaction.response.send_message(embed=_err("On Cooldown", f"You can beg again in **{_cd_str(rem)}**."), ephemeral=True)
            return

        # 20% chance of nothing
        if random.random() < 0.20:
            responses = [
                "Nobody gave you anything. How embarrassing.",
                "People walked right past you.",
                "Someone threw a pebble at you instead.",
            ]
            await interaction.response.send_message(
                embed=discord.Embed(title="🙏 Begging", description=random.choice(responses), color=0xE74C3C)
            )
            return

        earned = random.randint(1, 50)
        responses = [
            f"A kind stranger felt sorry for you and gave you",
            f"Someone tossed you some change —",
            f"A passing NPC took pity on you and handed you",
            f"You rattled your cup and collected",
        ]
        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + earned, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "beg", earned)

        e = discord.Embed(title="🙏 Begging", color=0x95A5A6)
        e.description = f"{random.choice(responses)} {_fmt(cfg, earned)}."
        await interaction.response.send_message(embed=e)

    # =====================================================================
    # NET WORTH
    # =====================================================================

    @app_commands.command(name="net_worth", description="View your full financial breakdown.")
    @app_commands.describe(user="User to check (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def net_worth(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        target = user or interaction.user
        await interaction.response.defer()

        cfg   = await _get_config(interaction.guild.id)
        data  = await _get_balance(interaction.guild.id, target.id)
        sym   = cfg.get("currency_symbol", DEFAULT_CURRENCY)

        # Inventory value
        store = await _get_store(interaction.guild.id)
        inv   = await _get_inventory(interaction.guild.id)
        uid   = str(target.id)
        inv_value = 0
        for iid, qty in inv.get(uid, {}).items():
            item_price = store.get(iid, {}).get("price", 0)
            inv_value += item_price * qty // 2  # sell value

        # Stock portfolio value
        prices    = await _get_live_prices(interaction.guild.id)
        portfolio = await _get_portfolio(interaction.guild.id)
        user_port = portfolio.get(uid, {})
        stock_value = sum(
            prices.get(t, {}).get("price", 0) * qty
            for t, qty in user_port.items()
        )

        wallet    = data["wallet"]
        bank      = data["bank"]
        net_total = wallet + bank + inv_value + stock_value

        e = discord.Embed(title=f"📊 {target.display_name}'s Net Worth", color=0xF1C40F)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="👛 Wallet",      value=f"{sym} {wallet:,}",     inline=True)
        e.add_field(name="🏦 Bank",        value=f"{sym} {bank:,}",       inline=True)
        e.add_field(name="🎒 Inventory",   value=f"{sym} {inv_value:,}",  inline=True)
        e.add_field(name="📈 Stocks",      value=f"{sym} {stock_value:,}",inline=True)
        e.add_field(name="💎 Total",       value=f"{sym} **{net_total:,}**", inline=False)

        # Milestone progress
        milestones = [
            (1_000_000_000_000_000, "👑 Quadrillionaire"),
            (1_000_000_000_000,     "💎 Trillionaire"),
            (1_000_000_000,         "💵 Billionaire"),
            (1_000_000,             "💰 Millionaire"),
        ]
        next_ms = next(((t, n) for t, n in milestones if net_total < t), None)
        if next_ms:
            needed = next_ms[0] - net_total
            e.add_field(name=f"Next: {next_ms[1]}", value=f"{sym} {needed:,} away", inline=False)

        e.set_footer(text=f"Requested by {interaction.user}")
        e.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=e)

    # =====================================================================
    # GAMBLING
    # =====================================================================

    @app_commands.command(name="coinflip", description="Flip a coin and bet on heads or tails.")
    @app_commands.describe(bet="Amount to bet", choice="heads or tails")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: str) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return

        result = random.choice(["heads", "tails"])
        win    = result == choice
        net    = bet if win else -bet
        nw     = data["wallet"] + net

        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "coinflip", net)
        extra = await self._maybe_award(interaction, nw, data["bank"]) if win else ""

        coin_emoji = "🪙 Heads" if result == "heads" else "🪙 Tails"
        e = discord.Embed(
            title="🪙 Coin Flip",
            description=(
                f"The coin landed on **{coin_emoji}**!\n"
                + (f"🎉 You won {_fmt(cfg, bet)}!{extra}" if win else f"❌ You lost {_fmt(cfg, bet)}.")
            ),
            color=0xF1C40F if win else 0xE74C3C,
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="crash", description="Bet on a rising multiplier — cash out before it crashes!")
    @app_commands.describe(bet="Amount to bet", cashout="Multiplier to auto cash-out at (e.g. 2.0)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def crash(self, interaction: discord.Interaction, bet: int, cashout: float) -> None:
        cfg  = await _get_config(interaction.guild.id)
        data = await _get_balance(interaction.guild.id, interaction.user.id)

        if bet <= 0 or bet > data["wallet"]:
            await interaction.response.send_message(
                embed=_err("Invalid Bet", f"You only have {_fmt(cfg, data['wallet'])} in wallet."), ephemeral=True
            )
            return
        if cashout < 1.01:
            await interaction.response.send_message(
                embed=_err("Invalid Cashout", "Cashout multiplier must be at least 1.01."), ephemeral=True
            )
            return

        await interaction.response.defer()

        # Generate crash point — exponential distribution, house edge
        crash_point = round(max(1.0, random.expovariate(0.7)), 2)
        win         = cashout <= crash_point

        # Animate the rising multiplier
        steps = []
        m = 1.0
        while m < min(cashout, crash_point) + 0.5:
            steps.append(round(m, 2))
            m += random.uniform(0.1, 0.4)
            if len(steps) > 8:
                break

        bar = " → ".join(f"**{s}x**" for s in steps[:6])

        if win:
            earned = int(bet * cashout) - bet
            nw     = min(data["wallet"] + earned, MAX_BALANCE)
            await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "crash_win", earned)
            extra = await self._maybe_award(interaction, nw, data["bank"])
            e = discord.Embed(
                title="📈 Crash — Cashed Out!",
                description=(
                    f"{bar} → ✅ **{cashout}x**\n\n"
                    f"💥 Crashed at **{crash_point}x**\n"
                    f"You cashed out in time and won {_fmt(cfg, earned)}!{extra}"
                ),
                color=0x2ECC71,
            )
        else:
            nw = data["wallet"] - bet
            await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
            await _add_audit(interaction.guild.id, interaction.user.id, "crash_loss", -bet)
            e = discord.Embed(
                title="📉 Crash — Wiped Out!",
                description=(
                    f"{bar} → 💥 **{crash_point}x**\n\n"
                    f"The rocket crashed before hitting your **{cashout}x** target.\n"
                    f"You lost {_fmt(cfg, bet)}."
                ),
                color=0xE74C3C,
            )

        await interaction.followup.send(embed=e)

    # =====================================================================
    # STOCKS
    # =====================================================================

    @app_commands.command(name="stock_prices", description="View current stock prices.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def stock_prices(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cfg    = await _get_config(interaction.guild.id)
        sym    = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        prices = await _get_live_prices(interaction.guild.id)

        e = discord.Embed(title="📈 Stock Market", color=0x2ECC71)
        e.set_footer(text="Prices fluctuate every 5 minutes  •  Use /stock_buy to invest")

        for ticker, data in prices.items():
            info  = BASE_STOCKS.get(ticker, {})
            price = data["price"]
            vol   = int(info.get("volatility", 0.1) * 100)
            e.add_field(
                name=f"{ticker} — {info.get('name', ticker)}",
                value=f"{sym} **{price:,}** per share  •  volatility: {vol}%",
                inline=False,
            )

        await interaction.followup.send(embed=e)

    @app_commands.command(name="stock_buy", description="Buy shares in a stock.")
    @app_commands.describe(ticker="Stock ticker symbol (e.g. ELURA)", shares="Number of shares to buy")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def stock_buy(self, interaction: discord.Interaction, ticker: str, shares: int) -> None:
        ticker = ticker.upper().strip()
        cfg    = await _get_config(interaction.guild.id)

        if ticker not in BASE_STOCKS:
            await interaction.response.send_message(
                embed=_err("Unknown Stock", f"`{ticker}` is not a valid ticker. Use `/stock_prices` to see available stocks."),
                ephemeral=True,
            )
            return
        if shares <= 0:
            await interaction.response.send_message(embed=_err("Invalid", "Shares must be greater than 0."), ephemeral=True)
            return

        prices    = await _get_live_prices(interaction.guild.id)
        price     = prices[ticker]["price"]
        total_cost = price * shares
        data      = await _get_balance(interaction.guild.id, interaction.user.id)

        if data["wallet"] < total_cost:
            await interaction.response.send_message(
                embed=_err("Insufficient Funds", f"You need {_fmt(cfg, total_cost)} but only have {_fmt(cfg, data['wallet'])} in wallet."),
                ephemeral=True,
            )
            return

        # Deduct and save
        await _set_balance(interaction.guild.id, interaction.user.id, data["wallet"] - total_cost, data["bank"])
        portfolio = await _get_portfolio(interaction.guild.id)
        uid       = str(interaction.user.id)
        if uid not in portfolio:
            portfolio[uid] = {}
        portfolio[uid][ticker] = portfolio[uid].get(ticker, 0) + shares
        await _save_portfolio(interaction.guild.id, portfolio)
        await _add_audit(interaction.guild.id, interaction.user.id, "stock_buy", -total_cost, f"{shares}x {ticker}")

        e = discord.Embed(title="📈 Stock Purchased", color=0x2ECC71)
        e.add_field(name="Stock",  value=f"{ticker} — {BASE_STOCKS[ticker]['name']}", inline=True)
        e.add_field(name="Shares", value=str(shares),                                 inline=True)
        e.add_field(name="Price",  value=_fmt(cfg, price) + " each",                 inline=True)
        e.add_field(name="Total Spent", value=_fmt(cfg, total_cost),                  inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="stock_sell", description="Sell shares from your portfolio.")
    @app_commands.describe(ticker="Stock ticker symbol", shares="Number of shares to sell (or 'all')")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def stock_sell(self, interaction: discord.Interaction, ticker: str, shares: str) -> None:
        ticker = ticker.upper().strip()
        cfg    = await _get_config(interaction.guild.id)

        if ticker not in BASE_STOCKS:
            await interaction.response.send_message(
                embed=_err("Unknown Stock", f"`{ticker}` is not a valid ticker."), ephemeral=True
            )
            return

        portfolio = await _get_portfolio(interaction.guild.id)
        uid       = str(interaction.user.id)
        owned     = portfolio.get(uid, {}).get(ticker, 0)

        if owned <= 0:
            await interaction.response.send_message(
                embed=_err("Not Owned", f"You don't own any {ticker} shares."), ephemeral=True
            )
            return

        qty = owned if shares.lower() == "all" else (int(shares) if shares.isdigit() else -1)
        if qty <= 0 or qty > owned:
            await interaction.response.send_message(
                embed=_err("Invalid Amount", f"You only own **{owned}** shares of {ticker}."), ephemeral=True
            )
            return

        prices   = await _get_live_prices(interaction.guild.id)
        price    = prices[ticker]["price"]
        proceeds = price * qty

        # Update portfolio
        portfolio[uid][ticker] -= qty
        if portfolio[uid][ticker] <= 0:
            del portfolio[uid][ticker]
        await _save_portfolio(interaction.guild.id, portfolio)

        data = await _get_balance(interaction.guild.id, interaction.user.id)
        nw   = min(data["wallet"] + proceeds, MAX_BALANCE)
        await _set_balance(interaction.guild.id, interaction.user.id, nw, data["bank"])
        await _add_audit(interaction.guild.id, interaction.user.id, "stock_sell", proceeds, f"{qty}x {ticker}")
        extra = await self._maybe_award(interaction, nw, data["bank"])

        e = discord.Embed(title="📉 Stock Sold", color=0xE74C3C)
        e.add_field(name="Stock",    value=f"{ticker} — {BASE_STOCKS[ticker]['name']}", inline=True)
        e.add_field(name="Shares",   value=str(qty),                                    inline=True)
        e.add_field(name="Price",    value=_fmt(cfg, price) + " each",                 inline=True)
        e.add_field(name="Proceeds", value=_fmt(cfg, proceeds),                         inline=True)
        if extra:
            e.description = extra
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="stock_portfolio", description="View your stock portfolio.")
    @app_commands.describe(user="User to view (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def stock_portfolio(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        target = user or interaction.user
        await interaction.response.defer()

        cfg       = await _get_config(interaction.guild.id)
        sym       = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        prices    = await _get_live_prices(interaction.guild.id)
        portfolio = await _get_portfolio(interaction.guild.id)
        uid       = str(target.id)
        user_port = portfolio.get(uid, {})

        e = discord.Embed(title=f"📊 {target.display_name}'s Portfolio", color=0x3498DB)
        e.set_thumbnail(url=target.display_avatar.url)

        if not user_port:
            e.description = "No stocks owned. Use `/stock_buy` to invest."
        else:
            total_value = 0
            for ticker, qty in user_port.items():
                price = prices.get(ticker, {}).get("price", 0)
                value = price * qty
                total_value += value
                info  = BASE_STOCKS.get(ticker, {})
                e.add_field(
                    name=f"{ticker} — {info.get('name', ticker)}",
                    value=f"**{qty}** shares × {sym} {price:,} = {sym} **{value:,}**",
                    inline=False,
                )
            e.add_field(name="💎 Total Value", value=f"{sym} **{total_value:,}**", inline=False)

        e.set_footer(text="Prices update every 5 minutes")
        await interaction.followup.send(embed=e)

    # =====================================================================
    # BITCOIN → GL COIN
    # =====================================================================

    @app_commands.command(name="btc", description="Convert real Bitcoin price to GL coins.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def btc(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        try:
            session = self._http or aiohttp.ClientSession()
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    raise ValueError("API error")
                data    = await resp.json()
                btc_usd = data["bitcoin"]["usd"]
        except Exception as exc:
            log.error("BTC fetch error: %s", exc)
            await interaction.followup.send(
                embed=_err("API Error", "Could not fetch Bitcoin price. Try again later.")
            )
            return

        cfg      = await _get_config(interaction.guild.id)
        sym      = cfg.get("currency_symbol", DEFAULT_CURRENCY)
        name     = cfg.get("currency_name",   DEFAULT_CURRENCY_NAME)

        # Conversion rate: 1 USD = 100 GL coins
        rate     = 100
        gl_value = int(btc_usd * rate)

        e = discord.Embed(title="₿ Bitcoin → GL Coin", color=0xF7931A)
        e.add_field(name="₿ Bitcoin Price",     value=f"**${btc_usd:,.2f} USD**",       inline=True)
        e.add_field(name=f"{sym} GL Coin Value", value=f"**{sym} {gl_value:,}**",        inline=True)
        e.add_field(name="📊 Rate",              value=f"1 USD = {rate} {name}",         inline=True)
        e.add_field(
            name="Examples",
            value=(
                f"0.001 BTC = {sym} {int(btc_usd * 0.001 * rate):,}\n"
                f"0.01 BTC = {sym} {int(btc_usd * 0.01 * rate):,}\n"
                f"0.1 BTC = {sym} {int(btc_usd * 0.1 * rate):,}"
            ),
            inline=False,
        )
        e.set_footer(text="Powered by CoinGecko  •  For fun only")
        e.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=e)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("EconomyExtraCog error: %s", error)
        msg = "❌ Something went wrong. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
    await bot.add_cog(EconomyExtraCog(bot))
