"""
cogs/welcome.py — Welcome & Leave system for Elura.

Stores config in the existing auto_mod_rules table (rule_type = 'welcome')
so no schema changes are needed.

Features:
  - Welcome message in configured channel
  - Custom welcome text
  - Member avatar thumbnail
  - Member count (You are member #500)
  - Leave message in a separate configured channel
  - /welcome setup, test, config, setext, disable
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

DEFAULT_WELCOME_TEXT = "Welcome to the server! We're glad to have you here."
RULE_TYPE = "welcome"


class WelcomeCog(commands.Cog, name="Welcome"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Config helpers ────────────────────────────────────────────────────

    async def _get_config(self, guild_id: int) -> dict:
        """Load welcome config from auto_mod_rules table."""
        rules = await db.get_automod_rules(guild_id)
        for rule in rules:
            if rule.get("rule_type") == RULE_TYPE:
                return rule.get("config") or {}
        return {}

    async def _save_config(self, guild_id: int, config: dict) -> None:
        """Merge and save welcome config into auto_mod_rules table."""
        existing = await self._get_config(guild_id)
        existing.update(config)
        await db.upsert_automod_rule(
            rule_type=RULE_TYPE,
            enabled=True,
            config=existing,
            guild_id=guild_id,
        )

    # ── Embed builders ────────────────────────────────────────────────────

    def _welcome_embed(self, member: discord.Member, welcome_text: str) -> discord.Embed:
        guild = member.guild
        count = guild.member_count
        e = discord.Embed(
            title=f"👋 Welcome to {guild.name}!",
            description=(
                f"{member.mention}, {welcome_text}\n\n"
                f"🎉 You are member **#{count:,}**!"
            ),
            color=0x2ECC71,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"Member #{count:,}  •  {guild.name}")
        e.timestamp = datetime.now(timezone.utc)
        return e

    def _leave_embed(self, member: discord.Member) -> discord.Embed:
        guild = member.guild
        e = discord.Embed(
            title="📤 Member Left",
            description=f"**{member}** has left the server.",
            color=0xE74C3C,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        if member.joined_at:
            e.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        e.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
        e.set_footer(text=f"User ID: {member.id}")
        e.timestamp = datetime.now(timezone.utc)
        return e

    # ── Events ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != GUILD_ID:
            return
        cfg = await self._get_config(member.guild.id)
        ch_id = cfg.get("welcome_channel_id")
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            return
        welcome_text = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT
        try:
            await ch.send(content=member.mention, embed=self._welcome_embed(member, welcome_text))
        except discord.Forbidden:
            log.warning("Cannot send welcome message to channel %s", ch_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != GUILD_ID:
            return
        cfg = await self._get_config(member.guild.id)
        ch_id = cfg.get("leave_channel_id")
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            await ch.send(embed=self._leave_embed(member))
        except discord.Forbidden:
            log.warning("Cannot send leave message to channel %s", ch_id)

    # ── Slash commands ────────────────────────────────────────────────────

    @app_commands.command(name="welcome_setup", description="Configure the welcome and leave system.")
    @app_commands.describe(
        welcome_channel="Channel for welcome messages",
        leave_channel="Channel for leave messages",
        welcome_text="Custom welcome text shown after the member mention",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        welcome_channel: discord.TextChannel,
        leave_channel: discord.TextChannel,
        welcome_text: str = DEFAULT_WELCOME_TEXT,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        await self._save_config(interaction.guild.id, {
            "welcome_channel_id": welcome_channel.id,
            "leave_channel_id":   leave_channel.id,
            "welcome_text":       welcome_text,
        })

        e = discord.Embed(title="✅ Welcome System Configured", color=0x2ECC71)
        e.add_field(name="Welcome Channel", value=welcome_channel.mention, inline=True)
        e.add_field(name="Leave Channel",   value=leave_channel.mention,   inline=True)
        e.add_field(name="Welcome Text",    value=welcome_text,             inline=False)
        e.set_footer(text="Use /welcome_test to preview.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="welcome_test", description="Preview the welcome message.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def welcome_test(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        cfg = await self._get_config(interaction.guild.id)
        welcome_text = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT
        await interaction.response.send_message(
            content="**Preview** (only you can see this)",
            embed=self._welcome_embed(interaction.user, welcome_text),
            ephemeral=True,
        )

    @app_commands.command(name="welcome_config", description="View current welcome system settings.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def welcome_config(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        cfg = await self._get_config(interaction.guild.id)
        wc  = cfg.get("welcome_channel_id")
        lc  = cfg.get("leave_channel_id")
        wt  = cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT

        e = discord.Embed(title="⚙️ Welcome System Config", color=0x3498DB)
        e.add_field(name="Welcome Channel", value=f"<#{wc}>" if wc else "❌ Not set", inline=True)
        e.add_field(name="Leave Channel",   value=f"<#{lc}>" if lc else "❌ Not set", inline=True)
        e.add_field(name="Welcome Text",    value=wt,                                  inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="welcome_setext", description="Update just the welcome text.")
    @app_commands.describe(text="New welcome text to display after the member mention")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def welcome_setext(self, interaction: discord.Interaction, text: str) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        await self._save_config(interaction.guild.id, {"welcome_text": text})
        await interaction.response.send_message(
            embed=_ok("Welcome Text Updated", f"New text:\n{text}"), ephemeral=True
        )

    @app_commands.command(name="welcome_disable", description="Disable welcome and/or leave messages.")
    @app_commands.describe(target="Which messages to disable")
    @app_commands.choices(target=[
        app_commands.Choice(name="Welcome messages", value="welcome"),
        app_commands.Choice(name="Leave messages",   value="leave"),
        app_commands.Choice(name="Both",             value="both"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def welcome_disable(self, interaction: discord.Interaction, target: str) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        update = {}
        if target in ("welcome", "both"):
            update["welcome_channel_id"] = None
        if target in ("leave", "both"):
            update["leave_channel_id"] = None
        await self._save_config(interaction.guild.id, update)
        label = "Welcome and leave messages" if target == "both" else f"{target.capitalize()} messages"
        await interaction.response.send_message(
            embed=_ok("Disabled", f"{label} have been disabled."), ephemeral=True
        )


# ── Embed shortcuts ───────────────────────────────────────────────────────

def _ok(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ECC71)

def _err(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xE74C3C)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
