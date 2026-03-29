"""
cogs/about.py — About command for Global League Bot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID

log = logging.getLogger(__name__)


class AboutCog(commands.Cog, name="About"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="about", description="About Global League Bot.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def about(self, interaction: discord.Interaction) -> None:
        latency = round(self.bot.latency * 1000)
        bot     = self.bot

        e = discord.Embed(
            title="🌐 Global League Bot • Elura",
            description="Built for Global League. Driven by its community.",
            color=0x5865F2,
        )

        if bot.user.avatar:
            e.set_thumbnail(url=bot.user.avatar.url)

        e.add_field(name="👨‍💻 Developer", value="Flyn", inline=True)
        e.add_field(name="⚙️ Version",    value="v1.0", inline=True)
        e.add_field(name="\u200b",         value="\u200b", inline=True)

        e.add_field(
            name="🎯 What it does",
            value=(
                "🛡 Moderation & AutoMod\n"
                "💰 Economy & Games\n"
                "🎟 Tickets & Welcome\n"
                "🔍 Search, Fun & Utility\n"
                "🚨 Anti-Raid Protection"
            ),
            inline=False,
        )

        e.add_field(
            name="📡 Status",
            value=f"🟢 Online • {latency}ms",
            inline=False,
        )

        e.add_field(
            name="⚡ Start here",
            value="`/help` — see everything the bot can do",
            inline=False,
        )

        e.add_field(
            name="🔒 Exclusive",
            value="Private. One server. No exceptions.",
            inline=False,
        )

        e.set_footer(text="Global League Bot v1.0 • Built by Flyn ⚡")
        e.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=e)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("AboutCog error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Something went wrong.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Something went wrong.", ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AboutCog(bot))
