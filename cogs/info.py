"""
cogs/info.py — User info, server info, anti-raid. Prefix: gl.
"""
from __future__ import annotations
import asyncio, logging, time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional
import discord
from discord.ext import commands
from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)
RULE_TYPE = "anti_raid"
DEFAULT_THRESHOLD = 10
DEFAULT_WINDOW    = 10
DEFAULT_ACTION    = "lockdown"

async def _get_raid_config(guild_id):
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == RULE_TYPE: return r.get("config") or {}
    return {}

async def _save_raid_config(guild_id, update):
    existing = await _get_raid_config(guild_id)
    existing.update(update)
    await db.upsert_automod_rule(RULE_TYPE, True, existing, guild_id)

def _account_age_str(created_at):
    days = (datetime.now(timezone.utc) - created_at).days
    if days < 1:   return f"{(datetime.now(timezone.utc) - created_at).seconds // 3600}h old ⚠️"
    if days < 7:   return f"{days}d old ⚠️"
    if days < 30:  return f"{days}d old"
    if days < 365: return f"{days // 30}mo old"
    return f"{days // 365}y old"

class InfoCog(commands.Cog, name="Info"):
    def __init__(self, bot):
        self.bot  = bot
        self._join_buckets: dict[int, deque] = {}
        self._raid_active:  dict[int, bool]  = {}
        self._start = datetime.now(timezone.utc)

    @commands.command(name="userinfo")
    @commands.guild_only()
    async def userinfo(self, ctx, user: discord.Member = None):
        """View member info. Usage: gl.userinfo [@user]"""
        target = user or ctx.author
        async with ctx.typing():
            cases, total = await db.get_cases(target.id, ctx.guild.id, page=1, page_size=1)
            notes        = await db.get_notes(target.id, ctx.guild.id)
        badges = []
        if target.id == ctx.guild.owner_id:      badges.append("👑 Server Owner")
        if target.guild_permissions.administrator: badges.append("🛡 Administrator")
        if target.bot:                            badges.append("🤖 Bot")
        if target.premium_since:                  badges.append("💎 Server Booster")
        roles     = [r.mention for r in reversed(target.roles) if r.id != ctx.guild.id]
        roles_str = " ".join(roles[:20]) or "None"
        if len(roles) > 20: roles_str += f" *+{len(roles)-20} more*"
        age_str = _account_age_str(target.created_at)
        if total == 0:         status = "🟢 Clean"
        elif total <= 2:       status = "🟡 Minor history"
        elif total <= 5:       status = "🟠 Moderate history"
        else:                  status = "🔴 Extensive history"
        e = discord.Embed(title=str(target), color=target.color if target.color.value else 0x5865F2)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="🆔 User ID",       value=f"`{target.id}`", inline=True)
        e.add_field(name="🏷 Nickname",       value=target.nick or "None", inline=True)
        e.add_field(name="🤖 Bot",            value="Yes" if target.bot else "No", inline=True)
        e.add_field(name="📅 Account Created", value=f"<t:{int(target.created_at.timestamp())}:F>\n{age_str}", inline=True)
        e.add_field(name="📥 Joined Server",   value=f"<t:{int(target.joined_at.timestamp())}:F>" if target.joined_at else "Unknown", inline=True)
        if target.premium_since:
            e.add_field(name="💎 Boosting", value=f"<t:{int(target.premium_since.timestamp())}:R>", inline=True)
        if badges: e.add_field(name="🏅 Badges", value="\n".join(badges), inline=False)
        e.add_field(name=f"🎭 Roles [{len(roles)}]", value=roles_str, inline=False)
        e.add_field(name="⚠️ Mod Cases",  value=str(total),      inline=True)
        e.add_field(name="📝 Notes",      value=str(len(notes)), inline=True)
        e.add_field(name="📊 Status",     value=status,          inline=True)
        e.set_footer(text=f"Requested by {ctx.author}")
        e.timestamp = datetime.now(timezone.utc)
        await ctx.send(embed=e)

    @commands.command(name="serverinfo")
    @commands.guild_only()
    async def serverinfo(self, ctx):
        """View server stats."""
        guild = ctx.guild
        text_channels  = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories     = len(guild.categories)
        total_members  = guild.member_count
        bots           = sum(1 for m in guild.members if m.bot)
        humans         = total_members - bots
        online         = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
        e = discord.Embed(title=guild.name, description=guild.description or "", color=0x5865F2)
        if guild.icon: e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="👑 Owner",      value=f"<@{guild.owner_id}>", inline=True)
        e.add_field(name="🆔 Server ID",  value=f"`{guild.id}`",         inline=True)
        e.add_field(name="📅 Created",    value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)
        e.add_field(name="👥 Members",    value=f"**Total:** {total_members:,}\n**Humans:** {humans:,}\n**Bots:** {bots:,}\n**Online:** {online:,}", inline=True)
        e.add_field(name="💬 Channels",   value=f"**Text:** {text_channels}\n**Voice:** {voice_channels}\n**Categories:** {categories}", inline=True)
        e.add_field(name="🎭 Roles",      value=str(len(guild.roles)-1), inline=True)
        e.add_field(name="💎 Boosts",     value=f"**Level:** {guild.premium_tier}\n**Count:** {guild.premium_subscription_count or 0}", inline=True)
        e.add_field(name="😀 Emojis",     value=f"{len(guild.emojis)}/{guild.emoji_limit}", inline=True)
        e.set_footer(text=f"Requested by {ctx.author}")
        e.timestamp = datetime.now(timezone.utc)
        await ctx.send(embed=e)

    @commands.command(name="botinfo")
    @commands.guild_only()
    async def botinfo(self, ctx):
        """View bot stats."""
        now   = datetime.now(timezone.utc)
        delta = now - self._start
        days  = delta.days; hours = delta.seconds // 3600; mins = (delta.seconds % 3600) // 60
        uptime  = f"{days}d {hours}h {mins}m"
        latency = round(self.bot.latency * 1000)
        cmds    = len(list(self.bot.commands))
        e = discord.Embed(title="🌐 Global League Bot", description="The ultimate all-in-one bot for Global League.", color=0x5865F2)
        if self.bot.user.avatar: e.set_thumbnail(url=self.bot.user.avatar.url)
        e.add_field(name="🤖 Bot Name",  value=str(self.bot.user),       inline=True)
        e.add_field(name="🆔 Bot ID",    value=f"`{self.bot.user.id}`",   inline=True)
        e.add_field(name="🏓 Latency",   value=f"{latency}ms",            inline=True)
        e.add_field(name="⏱ Uptime",     value=uptime,                    inline=True)
        e.add_field(name="📟 Commands",  value=str(cmds),                 inline=True)
        e.add_field(name="👥 Members",   value=f"{ctx.guild.member_count:,}", inline=True)
        e.add_field(name="🐍 Library",   value="discord.py 2.x",          inline=True)
        e.add_field(name="⚙️ Prefix",    value="`gl.`",                   inline=True)
        e.set_footer(text=f"Requested by {ctx.author}  •  Global League Bot")
        e.timestamp = now
        await ctx.send(embed=e)

    # ── Anti-raid ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != GUILD_ID: return
        guild_id = member.guild.id
        config   = await _get_raid_config(guild_id)
        if not config.get("enabled", False): return
        threshold = int(config.get("threshold", DEFAULT_THRESHOLD))
        window    = int(config.get("window",    DEFAULT_WINDOW))
        action    = config.get("action",        DEFAULT_ACTION)
        if self._raid_active.get(guild_id):
            await self._apply_raid_action(member, action, "Anti-Raid: server is in lockdown."); return
        if guild_id not in self._join_buckets: self._join_buckets[guild_id] = deque()
        bucket = self._join_buckets[guild_id]; now = time.monotonic()
        while bucket and now - bucket[0] > window: bucket.popleft()
        bucket.append(now)
        if len(bucket) >= threshold:
            self._raid_active[guild_id] = True
            bucket.clear()
            asyncio.create_task(self._handle_raid(member.guild, action, config))

    async def _handle_raid(self, guild, action, config):
        await _save_raid_config(guild.id, {"lockdown_active": True})
        locked_channels = []
        everyone = guild.default_role
        for ch in guild.text_channels:
            try:
                ow = ch.overwrites_for(everyone)
                if ow.send_messages is not False:
                    await ch.set_permissions(everyone, send_messages=False)
                    locked_channels.append(ch.id)
            except discord.Forbidden: pass
        await _save_raid_config(guild.id, {"locked_channels": locked_channels})
        cfg = await db.get_guild_config(guild.id)
        log_ch_id = cfg.get("log_channel_id") if cfg else None
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if isinstance(log_ch, discord.TextChannel):
                e = discord.Embed(title="🚨 RAID DETECTED — SERVER LOCKED DOWN",
                    description=f"**{len(locked_channels)} channels** locked.\nUse `gl.antiraid_unlock` to lift.",
                    color=0xFF0000)
                e.timestamp = datetime.now(timezone.utc)
                try: await log_ch.send(embed=e)
                except discord.Forbidden: pass

    async def _apply_raid_action(self, member, action, reason):
        try:
            if action == "kick":   await member.kick(reason=reason)
            elif action == "ban":  await member.ban(reason=reason, delete_message_days=0)
        except discord.Forbidden: pass

    @commands.command(name="antiraid_setup")
    @commands.guild_only()
    async def antiraid_setup(self, ctx, enabled: bool, threshold: int = 10,
                              window: int = 10, action: str = "lockdown"):
        """Configure anti-raid. Usage: gl.antiraid_setup <true/false> [threshold] [window] [lockdown|kick|ban]"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        await _save_raid_config(ctx.guild.id, {"enabled": enabled, "threshold": threshold,
                                                "window": window, "action": action})
        e = discord.Embed(title="✅ Anti-Raid Configured", color=0x2ECC71 if enabled else 0xE74C3C)
        e.add_field(name="Status",    value="✅ Enabled" if enabled else "❌ Disabled", inline=True)
        e.add_field(name="Threshold", value=f"{threshold} joins",                       inline=True)
        e.add_field(name="Window",    value=f"{window}s",                               inline=True)
        e.add_field(name="Action",    value=action.capitalize(),                        inline=True)
        await ctx.send(embed=e)

    @commands.command(name="antiraid_status")
    @commands.guild_only()
    async def antiraid_status(self, ctx):
        """View anti-raid status."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        config   = await _get_raid_config(ctx.guild.id)
        lockdown = self._raid_active.get(ctx.guild.id, False)
        e = discord.Embed(title="🛡 Anti-Raid Status", color=0xFF0000 if lockdown else 0x2ECC71)
        e.add_field(name="Enabled",   value="✅ Yes" if config.get("enabled") else "❌ No", inline=True)
        e.add_field(name="Lockdown",  value="🚨 ACTIVE" if lockdown else "✅ Clear",        inline=True)
        e.add_field(name="Threshold", value=f"{config.get('threshold', 10)} joins",        inline=True)
        e.add_field(name="Window",    value=f"{config.get('window', 10)}s",                inline=True)
        e.add_field(name="Action",    value=config.get("action", "lockdown").capitalize(), inline=True)
        await ctx.send(embed=e)

    @commands.command(name="antiraid_unlock")
    @commands.guild_only()
    async def antiraid_unlock(self, ctx):
        """Lift anti-raid lockdown."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        async with ctx.typing():
            guild  = ctx.guild
            config = await _get_raid_config(guild.id)
            locked = config.get("locked_channels", [])
            everyone = guild.default_role; unlocked = 0
            for ch_id in locked:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    try: await ch.set_permissions(everyone, send_messages=None); unlocked += 1
                    except discord.Forbidden: pass
            self._raid_active[guild.id] = False
            await _save_raid_config(guild.id, {"lockdown_active": False, "locked_channels": []})
        await ctx.send(embed=discord.Embed(title="✅ Lockdown Lifted",
                description=f"{unlocked} channels unlocked.", color=0x2ECC71))

async def setup(bot):
    await bot.add_cog(InfoCog(bot))
