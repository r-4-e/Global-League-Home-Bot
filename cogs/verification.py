"""
cogs/verification.py — Anti-alt account verification.

Posts a persistent "Verify" button. Clicking it mints a single-use,
short-lived token via database.py and replies with a link into the
web flow served by verify_web.py (mounted on the same Render process
as the bot). This cog never talks to the web server directly — the
two only share the `verify_tokens` / `verified_ips` Supabase tables.
"""

import secrets
import logging

import discord
from discord.ext import commands
from discord import app_commands

import config
from database import db

log = logging.getLogger("elura.verification")


class VerifyView(discord.ui.View):
    """timeout=None + a fixed custom_id survives bot restarts, as long
    as add_view() is called again on load (done in cog_load below)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.green,
        custom_id="glb_verify_button_v1",
        emoji="✅",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not config.PUBLIC_BASE_URL:
            await interaction.response.send_message(
                "Verification isn't configured yet (missing PUBLIC_BASE_URL / RENDER_EXTERNAL_URL). "
                "Ping staff.",
                ephemeral=True,
            )
            return

        token = secrets.token_urlsafe(32)
        ok = await db.create_verify_token(token, interaction.user.id, config.VERIFY_TOKEN_TTL_SECONDS)
        if not ok:
            await interaction.response.send_message(
                "Something went wrong generating your verification link. Please try again.",
                ephemeral=True,
            )
            return

        link = f"{config.PUBLIC_BASE_URL.rstrip('/')}/verify/{token}"
        minutes = config.VERIFY_TOKEN_TTL_SECONDS // 60
        await interaction.response.send_message(
            f"Click below to finish verifying. This link is single-use and expires in "
            f"{minutes} minutes:\n{link}",
            ephemeral=True,
        )


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(VerifyView())

    @commands.hybrid_command(
        name="postverify",
        description="Post the verification button in this channel.",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def postverify(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="Server Verification",
            description=(
                "Click **Verify** below to confirm your account and unlock the rest "
                "of the server. You'll get a private link that checks your account "
                "through Discord — no password or personal info needed."
            ),
            color=config.COLOR_INFO,
        )
        await ctx.send(embed=embed, view=VerifyView())

    @commands.hybrid_command(
        name="forceverify",
        description="Manually grant the Verified role to a member.",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def forceverify(self, ctx: commands.Context, member: discord.Member) -> None:
        role = ctx.guild.get_role(config.VERIFIED_ROLE_ID)
        if role is None:
            await ctx.send("VERIFIED_ROLE_ID doesn't match a role in this server.", ephemeral=True)
            return
        await member.add_roles(role, reason=f"Manually verified by {ctx.author}")
        await ctx.send(f"Granted {role.name} to {member.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
