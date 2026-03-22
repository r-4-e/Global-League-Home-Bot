"""
cogs/info.py — User Info, Server Info, and Anti-Raid system for Elura.

Commands:
  /userinfo  — full profile: join date, roles, account age, mod case count
  /serverinfo — server stats: members, channels, roles, boosts, creation date

Anti-Raid:
  - Detects mass joins within a configurable window
  - Auto-lockdown: kicks new joins, locks all channels
  - Alerts staff in log channel
  - /antiraid status  — view current settings
  - /antiraid setup   — configure threshold and action
  - /antiraid unlock  — manually lift lockdown
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

RULE_TYPE = "anti_raid"

# Default anti-raid settings
DEFAULT_THRESHOLD = 10   # joins within...
DEFAULT_WINDOW    = 10   # ...this many seconds triggers raid mode
DEFAULT_ACTION    = "lockdown"  # lockdown | kick | ban


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ECC71)

def _err(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xE74C3C)


async def _get_raid_config(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for rule in rules:
        if rule.get("rule_type") == RULE_TYPE:
            return rule.get("config") or {}
    return {}


async def _save_raid_config(guild_id: int, update: dict) -> None:
    existing = await _get_raid_config(guild_id)
    existing.update(update)
    await db.upsert_automod_rule(
        rule_type=RULE_TYPE,
        enabled=True,
        config=existing,
        guild_id=guild_id,
    )


def _account_age_str(created_at: datetime) -> str:
    delta = datetime.now(timezone.utc) - created_at
    days  = delta.days
    if days < 1:
        return f"{delta.seconds // 3600}h old ⚠️"
    if days < 7:
        return f"{days}d old ⚠️"
    if days < 30:
        return f"{days}d old"
    if days < 365:
        return f"{days // 30}mo old"
    return f"{days // 365}y old"


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class InfoCog(commands.Cog, name="Info"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # In-memory join timestamps for raid detection { guild_id: deque[timestamp] }
        self._join_buckets: dict[int, deque] = {}
        self._raid_active:  dict[int, bool]  = {}

    # =====================================================================
    # /userinfo
    # =====================================================================

    @app_commands.command(name="userinfo", description="View detailed info about a member.")
    @app_commands.describe(user="Member to look up (defaults to yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def userinfo(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                embed=_err("Not Found", "Could not find that member in this server."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=False)

        # Pull mod case count from DB
        cases, total = await db.get_cases(target.id, interaction.guild.id, page=1, page_size=1)
        notes        = await db.get_notes(target.id, interaction.guild.id)

        # Badges / status
        badges = []
        if target.id == interaction.guild.owner_id:
            badges.append("👑 Server Owner")
        if target.guild_permissions.administrator:
            badges.append("🛡 Administrator")
        if target.bot:
            badges.append("🤖 Bot")
        if target.premium_since:
            badges.append("💎 Server Booster")

        # Roles (skip @everyone)
        roles = [r.mention for r in reversed(target.roles) if r.id != interaction.guild.id]
        roles_str = " ".join(roles[:20]) or "None"
        if len(roles) > 20:
            roles_str += f" *+{len(roles) - 20} more*"

        # Account age
        age_str = _account_age_str(target.created_at)

        e = discord.Embed(
            title=str(target),
            color=target.color if target.color.value else 0x5865F2,
        )
        e.set_thumbnail(url=target.display_avatar.url)

        e.add_field(name="🆔 User ID",       value=f"`{target.id}`",                                     inline=True)
        e.add_field(name="🏷 Nickname",       value=target.nick or "None",                               inline=True)
        e.add_field(name="🤖 Bot",            value="Yes" if target.bot else "No",                       inline=True)
        e.add_field(
            name="📅 Account Created",
            value=f"<t:{int(target.created_at.timestamp())}:F>\n{age_str}",
            inline=True,
        )
        e.add_field(
            name="📥 Joined Server",
            value=f"<t:{int(target.joined_at.timestamp())}:F>" if target.joined_at else "Unknown",
            inline=True,
        )
        if target.premium_since:
            e.add_field(
                name="💎 Boosting Since",
                value=f"<t:{int(target.premium_since.timestamp())}:R>",
                inline=True,
            )
        if badges:
            e.add_field(name="🏅 Badges",    value="\n".join(badges),  inline=False)
        e.add_field(name=f"🎭 Roles [{len(roles)}]", value=roles_str,  inline=False)
        e.add_field(name="⚠️ Mod Cases",     value=str(total),         inline=True)
        e.add_field(name="📝 Staff Notes",   value=str(len(notes)),    inline=True)

        # Warn status indicator
        if total == 0:
            status = "🟢 Clean"
        elif total <= 2:
            status = "🟡 Minor history"
        elif total <= 5:
            status = "🟠 Moderate history"
        else:
            status = "🔴 Extensive history"
        e.add_field(name="📊 Status", value=status, inline=True)

        e.set_footer(text=f"Requested by {interaction.user}")
        e.timestamp = datetime.now(timezone.utc)

        await interaction.followup.send(embed=e)

    # =====================================================================
    # /serverinfo
    # =====================================================================

    @app_commands.command(name="serverinfo", description="View detailed info about this server.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild

        # Channel counts
        text_channels     = len(guild.text_channels)
        voice_channels    = len(guild.voice_channels)
        categories        = len(guild.categories)
        threads           = len(guild.threads)

        # Member counts
        total_members  = guild.member_count
        bots           = sum(1 for m in guild.members if m.bot)
        humans         = total_members - bots
        online         = sum(
            1 for m in guild.members
            if m.status != discord.Status.offline and not m.bot
        )

        # Boost info
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        # Verification level
        verification = str(guild.verification_level).replace("_", " ").title()

        e = discord.Embed(
            title=guild.name,
            description=guild.description or "",
            color=0x5865F2,
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            e.set_image(url=guild.banner.with_format("png").url)

        e.add_field(
            name="👑 Owner",
            value=f"<@{guild.owner_id}>",
            inline=True,
        )
        e.add_field(
            name="🆔 Server ID",
            value=f"`{guild.id}`",
            inline=True,
        )
        e.add_field(
            name="📅 Created",
            value=f"<t:{int(guild.created_at.timestamp())}:F>",
            inline=True,
        )
        e.add_field(
            name="👥 Members",
            value=(
                f"**Total:** {total_members:,}\n"
                f"**Humans:** {humans:,}\n"
                f"**Bots:** {bots:,}\n"
                f"**Online:** {online:,}"
            ),
            inline=True,
        )
        e.add_field(
            name="💬 Channels",
            value=(
                f"**Text:** {text_channels}\n"
                f"**Voice:** {voice_channels}\n"
                f"**Categories:** {categories}\n"
                f"**Threads:** {threads}"
            ),
            inline=True,
        )
        e.add_field(
            name="🎭 Roles",
            value=str(len(guild.roles) - 1),  # exclude @everyone
            inline=True,
        )
        e.add_field(
            name="💎 Boosts",
            value=(
                f"**Level:** {boost_level}\n"
                f"**Count:** {boost_count}"
            ),
            inline=True,
        )
        e.add_field(
            name="🔒 Verification",
            value=verification,
            inline=True,
        )
        e.add_field(
            name="😀 Emojis",
            value=f"{len(guild.emojis)}/{guild.emoji_limit}",
            inline=True,
        )

        e.set_footer(text=f"Requested by {interaction.user}")
        e.timestamp = datetime.now(timezone.utc)

        await interaction.followup.send(embed=e)

    # =====================================================================
    # Anti-Raid
    # =====================================================================

    # ── Join listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != GUILD_ID:
            return

        guild_id = member.guild.id
        config   = await _get_raid_config(guild_id)

        # Skip if anti-raid is not configured
        if not config.get("enabled", False):
            return

        threshold = int(config.get("threshold", DEFAULT_THRESHOLD))
        window    = int(config.get("window",    DEFAULT_WINDOW))
        action    = config.get("action",        DEFAULT_ACTION)

        # Already in lockdown — apply action immediately to new join
        if self._raid_active.get(guild_id):
            await self._apply_raid_action(member, action, "Anti-Raid: server is in lockdown.")
            return

        # Track join timestamps
        import time
        if guild_id not in self._join_buckets:
            self._join_buckets[guild_id] = deque()
        bucket = self._join_buckets[guild_id]
        now    = time.monotonic()

        # Evict old entries
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        bucket.append(now)

        # Trigger raid mode
        if len(bucket) >= threshold:
            log.warning("[Anti-Raid] Raid detected in guild %s — %d joins in %ds", guild_id, len(bucket), window)
            self._raid_active[guild_id] = True
            bucket.clear()
            asyncio.create_task(self._handle_raid(member.guild, action, config))

    # ── Raid handler ───────────────────────────────────────────────────────

    async def _handle_raid(
        self,
        guild: discord.Guild,
        action: str,
        config: dict,
    ) -> None:
        """Lock down the server and alert staff."""

        # Save lockdown state to DB
        await _save_raid_config(guild.id, {"lockdown_active": True})

        # Lock all text channels
        locked_channels = []
        everyone = guild.default_role
        for ch in guild.text_channels:
            try:
                overwrite = ch.overwrites_for(everyone)
                if overwrite.send_messages is not False:
                    await ch.set_permissions(everyone, send_messages=False)
                    locked_channels.append(ch.id)
            except discord.Forbidden:
                pass

        await _save_raid_config(guild.id, {"locked_channels": locked_channels})

        # Alert in log channel
        cfg = await db.get_guild_config(guild.id)
        log_ch_id = cfg.get("log_channel_id") if cfg else None
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if isinstance(log_ch, discord.TextChannel):
                e = discord.Embed(
                    title="🚨 RAID DETECTED — SERVER LOCKED DOWN",
                    description=(
                        f"**{len(locked_channels)} channels** have been locked.\n"
                        f"**Action on new joins:** `{action}`\n\n"
                        f"Use `/antiraid unlock` to lift the lockdown when it's safe."
                    ),
                    color=0xFF0000,
                )
                e.timestamp = datetime.now(timezone.utc)
                try:
                    await log_ch.send(embed=e)
                except discord.Forbidden:
                    pass

        log.warning("[Anti-Raid] Lockdown active in guild %s. %d channels locked.", guild.id, len(locked_channels))

    async def _apply_raid_action(
        self,
        member: discord.Member,
        action: str,
        reason: str,
    ) -> None:
        try:
            if action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=0)
            # lockdown = just let the channel locks prevent them from chatting
        except discord.Forbidden:
            pass

    # =====================================================================
    # /antiraid commands
    # =====================================================================

    @app_commands.command(name="antiraid_setup", description="Configure the anti-raid system.")
    @app_commands.describe(
        enabled="Enable or disable anti-raid detection",
        threshold="Number of joins that triggers raid mode (default 10)",
        window="Time window in seconds to count joins (default 10)",
        action="Action taken on raiders: lockdown, kick, or ban",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Lockdown (lock all channels)", value="lockdown"),
        app_commands.Choice(name="Kick raiders",                 value="kick"),
        app_commands.Choice(name="Ban raiders",                  value="ban"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def antiraid_setup(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        threshold: int = DEFAULT_THRESHOLD,
        window: int    = DEFAULT_WINDOW,
        action: str    = DEFAULT_ACTION,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        await _save_raid_config(interaction.guild.id, {
            "enabled":   enabled,
            "threshold": threshold,
            "window":    window,
            "action":    action,
        })

        e = discord.Embed(
            title="✅ Anti-Raid Configured",
            color=0x2ECC71 if enabled else 0xE74C3C,
        )
        e.add_field(name="Status",    value="✅ Enabled" if enabled else "❌ Disabled", inline=True)
        e.add_field(name="Threshold", value=f"{threshold} joins",                       inline=True)
        e.add_field(name="Window",    value=f"{window} seconds",                        inline=True)
        e.add_field(name="Action",    value=action.capitalize(),                        inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="antiraid_status", description="View current anti-raid configuration and status.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def antiraid_status(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        config = await _get_raid_config(interaction.guild.id)
        lockdown = self._raid_active.get(interaction.guild.id, False)

        e = discord.Embed(
            title="🛡 Anti-Raid Status",
            color=0xFF0000 if lockdown else 0x2ECC71,
        )
        e.add_field(name="Enabled",      value="✅ Yes" if config.get("enabled") else "❌ No",  inline=True)
        e.add_field(name="Lockdown",     value="🚨 ACTIVE" if lockdown else "✅ Clear",         inline=True)
        e.add_field(name="Threshold",    value=f"{config.get('threshold', DEFAULT_THRESHOLD)} joins", inline=True)
        e.add_field(name="Window",       value=f"{config.get('window', DEFAULT_WINDOW)}s",            inline=True)
        e.add_field(name="Action",       value=config.get("action", DEFAULT_ACTION).capitalize(),     inline=True)
        locked = len(config.get("locked_channels", []))
        if locked:
            e.add_field(name="Locked Channels", value=str(locked), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="antiraid_unlock", description="Lift the anti-raid lockdown and re-open all channels.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def antiraid_unlock(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild  = interaction.guild
        config = await _get_raid_config(guild.id)

        locked_channels: list = config.get("locked_channels", [])
        everyone = guild.default_role
        unlocked = 0

        for ch_id in locked_channels:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.set_permissions(everyone, send_messages=None)
                    unlocked += 1
                except discord.Forbidden:
                    pass

        # Clear lockdown state
        self._raid_active[guild.id] = False
        await _save_raid_config(guild.id, {
            "lockdown_active":  False,
            "locked_channels":  [],
        })

        # Alert log channel
        cfg = await db.get_guild_config(guild.id)
        log_ch_id = cfg.get("log_channel_id") if cfg else None
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if isinstance(log_ch, discord.TextChannel):
                e = discord.Embed(
                    title="✅ Lockdown Lifted",
                    description=(
                        f"**{unlocked} channels** have been unlocked.\n"
                        f"Lifted by {interaction.user.mention}"
                    ),
                    color=0x2ECC71,
                )
                e.timestamp = datetime.now(timezone.utc)
                try:
                    await log_ch.send(embed=e)
                except discord.Forbidden:
                    pass

        await interaction.followup.send(
            embed=_ok("Lockdown Lifted", f"{unlocked} channels have been unlocked."),
            ephemeral=True,
        )

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("InfoCog error: %s", error)
        msg = "❌ Something went wrong. Please try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InfoCog(bot))
