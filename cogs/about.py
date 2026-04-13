"""
cogs/about.py — About command for Global League Bot.
"""
from __future__ import annotations
from datetime import datetime, timezone
import discord
from discord.ext import commands
from config import GUILD_ID

class AboutCog(commands.Cog, name="About"):
    def __init__(self, bot):
        self.bot   = bot
        self._start = datetime.now(timezone.utc)

    @commands.command(name="about")
    @commands.guild_only()
    async def about(self, ctx):
        """About Global League Bot."""
        latency = round(self.bot.latency * 1000)
        bot     = self.bot
        now     = datetime.now(timezone.utc)
        delta   = now - self._start
        days    = delta.days
        hours   = delta.seconds // 3600
        mins    = (delta.seconds % 3600) // 60

        e = discord.Embed(
            title="🌐 Global League Bot • Elura",
            description="Built for Global League. Driven by its community.",
            color=0x5865F2,
        )
        if bot.user.avatar:
            e.set_thumbnail(url=bot.user.avatar.url)
        e.add_field(name="👨‍💻 Developer", value="Flyn",  inline=True)
        e.add_field(name="⚙️ Version",    value="v1.0",  inline=True)
        e.add_field(name="\u200b",         value="\u200b", inline=True)
        e.add_field(
            name="🎯 What it does",
            value=(
                "🛡 Moderation & AutoMod\n"
                "💰 Economy & Games\n"
                "🎟 Tickets & Welcome\n"
                "🔍 Search, Fun & Utility\n"
                "🚨 Anti-Raid Protection\n"
                "🗳️ Elections"
            ),
            inline=False,
        )
        e.add_field(name="📡 Status",    value=f"🟢 Online • {latency}ms", inline=False)
        e.add_field(name="⏱ Uptime",     value=f"{days}d {hours}h {mins}m", inline=False)
        e.add_field(name="⚡ Start here", value="`gl.help` — see everything", inline=False)
        e.add_field(name="🔒 Exclusive",  value="Private. One server. No exceptions.", inline=False)
        e.set_footer(text="Global League Bot v1.0 • Built by Flyn ⚡")
        e.timestamp = now
        await ctx.send(embed=e)

async def setup(bot):
    await bot.add_cog(AboutCog(bot))
