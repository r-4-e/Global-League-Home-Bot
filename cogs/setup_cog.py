"""
cogs/setup_cog.py — Interactive /setup command for Elura.

5-step wizard:
  Step 1 — Select log channel       (ChannelSelect)
  Step 2 — Select muted role        (RoleSelect + skip)
  Step 3 — Assign staff role        (RoleSelect + skip)
  Step 4 — Toggle automod on/off    (button)
  Step 5 — Confirm & save

Also provides /config to view/edit settings post-setup.
Also provides /perm_override to manage role-based command overrides.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils import embeds
from utils.cache import guild_config_cache, automod_rules_cache
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup View — 5-step wizard
# ---------------------------------------------------------------------------

class SetupView(discord.ui.View):
    """
    Interactive setup wizard.
    State machine: CHANNEL → MUTED_ROLE → STAFF_ROLE → AUTOMOD → CONFIRM
    """

    STEPS = ["CHANNEL", "MUTED_ROLE", "STAFF_ROLE", "AUTOMOD", "CONFIRM"]

    def __init__(self, invoker: discord.Member, guild: discord.Guild) -> None:
        super().__init__(timeout=300)
        self.invoker          = invoker
        self.guild            = guild
        self.log_channel_id:  Optional[int] = None
        self.muted_role_id:   Optional[int] = None
        self.staff_role_id:   Optional[int] = None
        self.automod_enabled: bool          = True
        self._step = "CHANNEL"
        self._refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "❌ Only the person who ran /setup can interact with this.", ephemeral=True
            )
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        step_labels = {
            "CHANNEL":    ("1️⃣ Select Log Channel",  "Choose where moderation logs will be posted."),
            "MUTED_ROLE": ("2️⃣ Select Muted Role",   "Choose the role given to muted members."),
            "STAFF_ROLE": ("3️⃣ Assign Staff Role",   "Choose the role that grants staff privileges (used for permission overrides)."),
            "AUTOMOD":    ("4️⃣ AutoMod Toggle",      "Enable or disable the automod system."),
            "CONFIRM":    ("5️⃣ Confirm & Save",       "Review your settings and save."),
        }
        title, desc = step_labels.get(self._step, ("Setup", ""))
        step_num    = self.STEPS.index(self._step) + 1

        e = discord.Embed(title=f"⚙️ Elura Setup — {title}", description=desc, color=0x9B59B6)
        if self.log_channel_id:
            e.add_field(name="Log Channel", value=f"<#{self.log_channel_id}>",    inline=True)
        if self.muted_role_id:
            e.add_field(name="Muted Role",  value=f"<@&{self.muted_role_id}>",    inline=True)
        if self.staff_role_id:
            e.add_field(name="Staff Role",  value=f"<@&{self.staff_role_id}>",    inline=True)
        e.add_field(name="AutoMod", value="✅ Enabled" if self.automod_enabled else "❌ Disabled", inline=True)
        e.set_footer(text=f"Requested by {self.invoker}  •  Step {step_num}/{len(self.STEPS)}")
        return e

    def _refresh_components(self) -> None:
        self.clear_items()
        if self._step == "CHANNEL":
            self.add_item(LogChannelSelect())
        elif self._step == "MUTED_ROLE":
            self.add_item(MutedRoleSelect())
            self.add_item(SkipButton("skip_muted", "Skip (no muted role)"))
        elif self._step == "STAFF_ROLE":
            self.add_item(StaffRoleSelect())
            self.add_item(SkipButton("skip_staff", "Skip (no staff role)"))
        elif self._step == "AUTOMOD":
            self.add_item(AutomodToggleButton(self.automod_enabled))
            self.add_item(NextButton("next_automod", "Next ➜"))
        elif self._step == "CONFIRM":
            self.add_item(ConfirmButton())
            self.add_item(CancelButton())

    def _advance(self) -> None:
        idx = self.STEPS.index(self._step)
        if idx + 1 < len(self.STEPS):
            self._step = self.STEPS[idx + 1]
        self._refresh_components()

    async def _save(self, interaction: discord.Interaction) -> None:
        ok = await db.upsert_guild_config({
            "guild_id":        self.guild.id,
            "log_channel_id":  self.log_channel_id,
            "muted_role_id":   self.muted_role_id,
            "staff_role_id":   self.staff_role_id,
            "automod_enabled": self.automod_enabled,
            "setup_complete":  True,
        })
        guild_config_cache.invalidate(f"log_ch_{self.guild.id}")
        guild_config_cache.invalidate(f"cfg_{self.guild.id}")
        automod_rules_cache.invalidate("rules")

        if ok:
            desc = (
                "Elura is configured and ready.\n\n"
                + (f"**Log Channel:** <#{self.log_channel_id}>\n"  if self.log_channel_id else "**Log Channel:** Not set\n")
                + (f"**Muted Role:** <@&{self.muted_role_id}>\n"   if self.muted_role_id  else "**Muted Role:** Not set\n")
                + (f"**Staff Role:** <@&{self.staff_role_id}>\n"   if self.staff_role_id  else "**Staff Role:** Not set\n")
                + f"**AutoMod:** {'✅ Enabled' if self.automod_enabled else '❌ Disabled'}"
            )
            await interaction.response.edit_message(
                embed=discord.Embed(title="✅ Setup Complete!", description=desc, color=0x2ECC71),
                view=None,
            )
        else:
            await interaction.response.edit_message(
                embed=embeds.error("Save Failed", "Could not save config. Check Supabase connection."),
                view=None,
            )
        self.stop()


# ---------------------------------------------------------------------------
# UI sub-components
# ---------------------------------------------------------------------------

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Select the log channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view.log_channel_id = self.values[0].id
        view._advance()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class MutedRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Select the muted role…", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view.muted_role_id = self.values[0].id
        view._advance()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class StaffRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Select the staff role…", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view.staff_role_id = self.values[0].id
        view._advance()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class SkipButton(discord.ui.Button):
    def __init__(self, custom_id: str, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view._advance()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class AutomodToggleButton(discord.ui.Button):
    def __init__(self, enabled: bool) -> None:
        label = "✅ AutoMod: ON — click to disable" if enabled else "❌ AutoMod: OFF — click to enable"
        style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view.automod_enabled = not view.automod_enabled
        view._refresh_components()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class NextButton(discord.ui.Button):
    def __init__(self, custom_id: str, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        view._advance()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class ConfirmButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="✅ Save Configuration", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupView = self.view  # type: ignore[assignment]
        await view._save(interaction)


class CancelButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="✖ Cancel", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=embeds.error("Setup Cancelled", "No changes were saved."), view=None
        )
        self.view.stop()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class SetupCog(commands.Cog, name="Setup"):
    """Server configuration commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /setup ────────────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Configure Elura for this server.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def setup(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(
                embed=embeds.error("Permission Denied", "You need **Administrator** to run /setup."),
                ephemeral=True,
            )
            return
        view = SetupView(invoker=interaction.user, guild=interaction.guild)
        await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)

    # ── /config ───────────────────────────────────────────────────────────

    @app_commands.command(name="config", description="View the current server configuration.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def config(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=embeds.error("Permission Denied", msg), ephemeral=True)
            return

        cfg = await db.get_guild_config(interaction.guild.id)
        if not cfg:
            await interaction.response.send_message(
                embed=embeds.warning("Not Configured", "Run /setup first."), ephemeral=True
            )
            return

        lc = cfg.get("log_channel_id")
        mr = cfg.get("muted_role_id")
        sr = cfg.get("staff_role_id")

        e = discord.Embed(title="⚙️ Current Configuration", color=0x3498DB)
        e.add_field(name="Log Channel",    value=f"<#{lc}>"  if lc else "Not set", inline=True)
        e.add_field(name="Muted Role",     value=f"<@&{mr}>" if mr else "Not set", inline=True)
        e.add_field(name="Staff Role",     value=f"<@&{sr}>" if sr else "Not set", inline=True)
        e.add_field(name="AutoMod",        value="✅ Enabled" if cfg.get("automod_enabled") else "❌ Disabled", inline=True)
        e.add_field(name="Setup Complete", value="✅ Yes"     if cfg.get("setup_complete")  else "❌ No",       inline=True)

        overrides = await db.get_permission_overrides(interaction.guild.id)
        if overrides:
            lines = [
                f"<@&{o['role_id']}> → `/{o['command']}` {'✅ Allowed' if o['allowed'] else '❌ Denied'}"
                for o in overrides[:10]
            ]
            e.add_field(name="Permission Overrides", value="\n".join(lines), inline=False)

        e.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /perm_override ────────────────────────────────────────────────────

    @app_commands.command(
        name="perm_override",
        description="Allow or deny a role from using a specific slash command.",
    )
    @app_commands.describe(
        role="The role to configure",
        command="The slash command name, e.g. ban, kick, warn",
        allowed="True to allow, False to deny",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def perm_override(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
        allowed: bool,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=embeds.error("Permission Denied", msg), ephemeral=True)
            return

        success = await db.set_permission_override(
            role_id=role.id,
            command=command.lower().strip(),
            allowed=allowed,
            guild_id=interaction.guild.id,
        )
        if success:
            state = "✅ **allowed**" if allowed else "❌ **denied**"
            await interaction.response.send_message(
                embed=embeds.success(
                    "Override Set",
                    f"{role.mention} is now {state} to use `/{command.lower().strip()}`.",
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error("Failed", "Could not save the override. Check Supabase."),
                ephemeral=True,
            )

    # ── Error handler ─────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("SetupCog error: %s", error)
        msg = "❌ Something went wrong. Please try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embeds.error("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=embeds.error("Error", msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
