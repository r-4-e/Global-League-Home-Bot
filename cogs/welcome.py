"""
cogs/welcome.py — DMs new members when they join, prompting them to verify.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import GUILD_ID

log = logging.getLogger(__name__)

VERIFY_CHANNEL_ID = 1520765786032046112


class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID or member.bot:
            return

        verify_channel = member.guild.get_channel(VERIFY_CHANNEL_ID)
        channel_mention = verify_channel.mention if verify_channel else "#verify"

        e = discord.Embed(
            title="👋 Welcome to Global League!",
            description=(
                f"To access the server, you'll need to verify your account — "
                f"it's quick and easy, no password or personal info needed.\n\n"
                f"**Here's how:**\n"
                f"1. Head over to {channel_mention}\n"
                f"2. Click the green **✅ Verify** button\n"
                f"3. You'll receive a private link — follow it to complete verification\n\n"
                f"It only takes a few seconds. If you run into any issues, feel free to "
                f"ping a staff member. See you inside! 🌍"
            ),
            color=0x5865F2,
        )
        e.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        e.set_footer(text="Global League — Verification System")

        try:
            await member.send(embed=e)
        except (discord.Forbidden, discord.HTTPException):
            # User has DMs disabled — silently ignore
            log.info("welcome: could not DM %s (%s) — DMs likely disabled.", member, member.id)


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
