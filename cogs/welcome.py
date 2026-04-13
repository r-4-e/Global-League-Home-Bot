"""
cogs/welcome.py — Welcome & Leave system. Prefix: gl.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
import discord
from discord.ext import commands
from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)
RULE_TYPE = "welcome"
DEFAULT_WELCOME_TEXT = "Welcome to the server! We're glad to have you here."

class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot):
        self.bot = bot

    async def _get_config(self, guild_id):
        rules = await db.get_automod_rules(guild_id)
        for rule in rules:
            if rule.get("rule_type") == RULE_TYPE:
                return rule.get("config") or {}
        return {}

    async def _save_config(self, guild_id, config):
        existing = await self._get_config(guild_id)
        existing.update(config)
        await db.upsert_automod_rule(RULE_TYPE, True, existing, guild_id)

    def _welcome_embed(self, member, welcome_text):
        guild = member.guild
        count = guild.member_count
        e = discord.Embed(title=f"👋 Welcome to {guild.name}!",
            description=f"{member.mention}, {welcome_text}\n\n🎉 You are member **#{count:,}**!",
            color=0x2ECC71)
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"Member #{count:,}  •  {guild.name}")
        e.timestamp = datetime.now(timezone.utc)
        return e

    def _leave_embed(self, member):
        e = discord.Embed(title="📤 Member Left",
            description=f"**{member}** has left the server.", color=0xE74C3C)
        e.set_thumbnail(url=member.display_avatar.url)
        if member.joined_at:
            e.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        e.add_field(name="Members", value=f"{member.guild.member_count:,}", inline=True)
        e.set_footer(text=f"User ID: {member.id}")
        e.timestamp = datetime.now(timezone.utc)
        return e

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != GUILD_ID: return
        cfg = await self._get_config(member.guild.id)
        ch_id = cfg.get("welcome_channel_id")
        if not ch_id: return
        ch = member.guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel): return
        welcome_text = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT
        try: await ch.send(content=member.mention, embed=self._welcome_embed(member, welcome_text))
        except discord.Forbidden: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id != GUILD_ID: return
        cfg = await self._get_config(member.guild.id)
        ch_id = cfg.get("leave_channel_id")
        if not ch_id: return
        ch = member.guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel): return
        try: await ch.send(embed=self._leave_embed(member))
        except discord.Forbidden: pass

    @commands.command(name="welcome_setup")
    @commands.guild_only()
    async def welcome_setup(self, ctx, welcome_channel: discord.TextChannel,
                             leave_channel: discord.TextChannel, *, welcome_text: str = DEFAULT_WELCOME_TEXT):
        """Setup welcome system. Usage: gl.welcome_setup #welcome #goodbye [custom text]"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        await self._save_config(ctx.guild.id, {
            "welcome_channel_id": welcome_channel.id,
            "leave_channel_id":   leave_channel.id,
            "welcome_text":       welcome_text,
        })
        e = discord.Embed(title="✅ Welcome System Configured", color=0x2ECC71)
        e.add_field(name="Welcome Channel", value=welcome_channel.mention, inline=True)
        e.add_field(name="Leave Channel",   value=leave_channel.mention,   inline=True)
        e.add_field(name="Welcome Text",    value=welcome_text,             inline=False)
        await ctx.send(embed=e)

    @commands.command(name="welcome_setext")
    @commands.guild_only()
    async def welcome_setext(self, ctx, *, text: str):
        """Update welcome text. Usage: gl.welcome_setext <text>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        await self._save_config(ctx.guild.id, {"welcome_text": text})
        await ctx.send(embed=discord.Embed(title="✅ Welcome Text Updated", description=text, color=0x2ECC71))

    @commands.command(name="welcome_test")
    @commands.guild_only()
    async def welcome_test(self, ctx):
        """Preview welcome message."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        cfg = await self._get_config(ctx.guild.id)
        welcome_text = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT
        await ctx.send(content="**Preview:**", embed=self._welcome_embed(ctx.author, welcome_text))

    @commands.command(name="welcome_config")
    @commands.guild_only()
    async def welcome_config(self, ctx):
        """View welcome settings."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        cfg = await self._get_config(ctx.guild.id)
        wc = cfg.get("welcome_channel_id"); lc = cfg.get("leave_channel_id")
        wt = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT
        e = discord.Embed(title="⚙️ Welcome Config", color=0x3498DB)
        e.add_field(name="Welcome Channel", value=f"<#{wc}>" if wc else "❌ Not set", inline=True)
        e.add_field(name="Leave Channel",   value=f"<#{lc}>" if lc else "❌ Not set", inline=True)
        e.add_field(name="Welcome Text",    value=wt, inline=False)
        await ctx.send(embed=e)

    @commands.command(name="welcome_disable")
    @commands.guild_only()
    async def welcome_disable(self, ctx, target: str):
        """Disable welcome/leave messages. Usage: gl.welcome_disable <welcome|leave|both>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        update = {}
        if target in ("welcome","both"): update["welcome_channel_id"] = None
        if target in ("leave","both"):   update["leave_channel_id"]   = None
        await self._save_config(ctx.guild.id, update)
        label = "Welcome and leave" if target == "both" else target.capitalize()
        await ctx.send(embed=discord.Embed(title=f"✅ {label} messages disabled.", color=0x2ECC71))

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
