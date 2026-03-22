"""
cogs/tickets.py — Ticket System for Elura.

Features:
  - /ticket_setup  → sends a panel with a button to a channel
  - Button opens a modal asking for reason/topic
  - Creates a private channel per ticket
  - Staff control panel inside ticket (Close / Claim buttons)
  - Transcript generated and saved to a transcript channel on close
  - Config stored in auto_mod_rules table (no schema changes)
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

RULE_TYPE = "tickets"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ECC71)

def _err(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xE74C3C)

def _info(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=f"ℹ️ {title}", description=desc, color=0x3498DB)


async def _get_ticket_config(guild_id: int) -> dict:
    rules = await db.get_automod_rules(guild_id)
    for rule in rules:
        if rule.get("rule_type") == RULE_TYPE:
            return rule.get("config") or {}
    return {}


async def _save_ticket_config(guild_id: int, update: dict) -> None:
    existing = await _get_ticket_config(guild_id)
    existing.update(update)
    await db.upsert_automod_rule(
        rule_type=RULE_TYPE,
        enabled=True,
        config=existing,
        guild_id=guild_id,
    )


def _ticket_number(config: dict) -> int:
    return config.get("ticket_count", 0) + 1


# ---------------------------------------------------------------------------
# Modal — reason input
# ---------------------------------------------------------------------------

class TicketReasonModal(discord.ui.Modal, title="Open a Ticket"):
    reason = discord.ui.TextInput(
        label="Reason / Topic",
        placeholder="Briefly describe your issue or question…",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=500,
    )

    def __init__(self, cog: "TicketCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_ticket(interaction, self.reason.value)


# ---------------------------------------------------------------------------
# Ticket panel button (persistent)
# ---------------------------------------------------------------------------

class TicketPanelView(discord.ui.View):
    """Persistent view attached to the ticket panel message."""

    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🎟 Open a Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:open",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Check if user already has an open ticket
        config = await _get_ticket_config(interaction.guild.id)
        open_tickets: dict = config.get("open_tickets", {})
        uid = str(interaction.user.id)

        if uid in open_tickets:
            ch = interaction.guild.get_channel(open_tickets[uid])
            if ch:
                await interaction.response.send_message(
                    embed=_err(
                        "Already Open",
                        f"You already have an open ticket: {ch.mention}",
                    ),
                    ephemeral=True,
                )
                return
            else:
                # Channel was deleted manually — clean up
                del open_tickets[uid]
                await _save_ticket_config(
                    interaction.guild.id, {"open_tickets": open_tickets}
                )

        await interaction.response.send_modal(TicketReasonModal(self.cog))


# ---------------------------------------------------------------------------
# Ticket control panel (inside the ticket channel)
# ---------------------------------------------------------------------------

class TicketControlView(discord.ui.View):
    """Buttons inside the ticket channel — Close and Claim."""

    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.close_ticket(interaction)

    @discord.ui.button(
        label="🙋 Claim Ticket",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:claim",
    )
    async def claim_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        config = await _get_ticket_config(interaction.guild.id)
        staff_role_id = config.get("staff_role_id")

        # Check invoker is staff
        member = interaction.user
        if not isinstance(member, discord.Member):
            return
        if staff_role_id:
            role_ids = {r.id for r in member.roles}
            if int(staff_role_id) not in role_ids and not member.guild_permissions.administrator:
                await interaction.response.send_message(
                    embed=_err("Not Staff", "Only staff members can claim tickets."),
                    ephemeral=True,
                )
                return

        # Update channel topic to show claimer
        try:
            await interaction.channel.edit(
                topic=f"📌 Claimed by {member} ({member.id})"
            )
        except discord.Forbidden:
            pass

        e = discord.Embed(
            title="🙋 Ticket Claimed",
            description=f"This ticket has been claimed by {member.mention}.",
            color=0x3498DB,
        )
        e.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=e)


# ---------------------------------------------------------------------------
# Confirm close view
# ---------------------------------------------------------------------------

class ConfirmCloseView(discord.ui.View):
    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=30)
        self.cog = cog

    @discord.ui.button(label="✅ Confirm Close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.close_ticket(interaction, confirmed=True)
        self.stop()

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=_info("Cancelled", "Ticket close cancelled."), ephemeral=True
        )
        self.stop()


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class TicketCog(commands.Cog, name="Tickets"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Re-register persistent views on startup."""
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketControlView(self))

    # ── Create ticket ─────────────────────────────────────────────────────

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        reason: str,
    ) -> None:
        guild  = interaction.guild
        member = interaction.user
        config = await _get_ticket_config(guild.id)

        category_id    = config.get("ticket_category_id")
        staff_role_id  = config.get("staff_role_id")
        ticket_count   = _ticket_number(config)

        category = guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        # Permission overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me:           discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                manage_messages=True, read_message_history=True,
            ),
            member:             discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
            ),
        }
        if staff_role_id:
            staff_role = guild.get_role(int(staff_role_id))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    manage_messages=True,
                )

        # Create channel
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_count:04d}",
                category=category,
                overwrites=overwrites,
                topic=f"Ticket #{ticket_count:04d} | {member} | {reason[:80]}",
                reason=f"Ticket opened by {member}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=_err("Failed", "I don't have permission to create channels."),
                ephemeral=True,
            )
            return

        # Save open ticket
        open_tickets = config.get("open_tickets", {})
        open_tickets[str(member.id)] = channel.id
        await _save_ticket_config(guild.id, {
            "open_tickets":  open_tickets,
            "ticket_count":  ticket_count,
        })

        # Send control panel inside ticket
        panel_embed = discord.Embed(
            title=f"🎟 Ticket #{ticket_count:04d}",
            description=(
                f"**Opened by:** {member.mention}\n"
                f"**Reason:** {reason}\n\n"
                f"Support staff will be with you shortly.\n"
                f"Use the buttons below to manage this ticket."
            ),
            color=0x5865F2,
        )
        panel_embed.set_thumbnail(url=member.display_avatar.url)
        panel_embed.set_footer(text=f"Ticket #{ticket_count:04d}  •  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")

        await channel.send(
            content=f"{member.mention}" + (f" | <@&{staff_role_id}>" if staff_role_id else ""),
            embed=panel_embed,
            view=TicketControlView(self),
        )

        await interaction.followup.send(
            embed=_ok("Ticket Opened", f"Your ticket has been created: {channel.mention}"),
            ephemeral=True,
        )

    # ── Close ticket ──────────────────────────────────────────────────────

    async def close_ticket(
        self,
        interaction: discord.Interaction,
        confirmed: bool = False,
    ) -> None:
        channel = interaction.channel
        guild   = interaction.guild
        config  = await _get_ticket_config(guild.id)

        # Verify this is actually a ticket channel
        open_tickets: dict = config.get("open_tickets", {})
        owner_id = next(
            (uid for uid, ch_id in open_tickets.items() if ch_id == channel.id),
            None,
        )

        if owner_id is None:
            await interaction.followup.send(
                embed=_err("Not a Ticket", "This command can only be used inside a ticket channel."),
                ephemeral=True,
            )
            return

        # First press — ask for confirmation
        if not confirmed:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ Close Ticket?",
                    description="Are you sure you want to close this ticket? A transcript will be saved.",
                    color=0xF39C12,
                ),
                view=ConfirmCloseView(self),
                ephemeral=True,
            )
            return

        # Generate transcript
        transcript = await self._generate_transcript(channel, guild, owner_id, config)

        # Post transcript to transcript channel if configured
        transcript_ch_id = config.get("transcript_channel_id")
        if transcript_ch_id:
            transcript_ch = guild.get_channel(int(transcript_ch_id))
            if isinstance(transcript_ch, discord.TextChannel):
                t_embed = discord.Embed(
                    title=f"📄 Transcript — {channel.name}",
                    description=(
                        f"**Opened by:** <@{owner_id}>\n"
                        f"**Closed by:** {interaction.user.mention}\n"
                        f"**Channel:** #{channel.name}"
                    ),
                    color=0x95A5A6,
                )
                t_embed.timestamp = datetime.now(timezone.utc)
                file = discord.File(
                    io.BytesIO(transcript.encode("utf-8")),
                    filename=f"{channel.name}-transcript.txt",
                )
                try:
                    await transcript_ch.send(embed=t_embed, file=file)
                except discord.Forbidden:
                    log.warning("Cannot send transcript to channel %s", transcript_ch_id)

        # Remove from open tickets
        open_tickets.pop(str(owner_id), None)
        await _save_ticket_config(guild.id, {"open_tickets": open_tickets})

        # Notify and delete
        await channel.send(
            embed=discord.Embed(
                title="🔒 Ticket Closed",
                description=f"Closed by {interaction.user.mention}. This channel will be deleted in 5 seconds.",
                color=0xE74C3C,
            )
        )

        await interaction.followup.send(
            embed=_ok("Ticket Closed", "The ticket has been closed and a transcript was saved."),
            ephemeral=True,
        )

        import asyncio
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.Forbidden:
            log.warning("Cannot delete ticket channel %s", channel.id)

    # ── Transcript generator ──────────────────────────────────────────────

    async def _generate_transcript(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        owner_id: str,
        config: dict,
    ) -> str:
        lines = [
            f"TICKET TRANSCRIPT",
            f"=================",
            f"Channel  : #{channel.name}",
            f"Server   : {guild.name}",
            f"Opened by: {owner_id}",
            f"Exported : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            f"",
            f"─── Messages ───",
            f"",
        ]
        try:
            async for msg in channel.history(limit=500, oldest_first=True):
                ts   = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                name = str(msg.author)
                content = msg.content or "[embed/attachment]"
                lines.append(f"[{ts}] {name}: {content}")
        except discord.Forbidden:
            lines.append("[Could not fetch message history]")

        return "\n".join(lines)

    # ── /ticket_setup ──────────────────────────────────────────────────────

    @app_commands.command(
        name="ticket_setup",
        description="Send the ticket panel to a channel and configure the ticket system.",
    )
    @app_commands.describe(
        panel_channel="Channel where the ticket open button will be posted",
        transcript_channel="Channel where transcripts are saved on close",
        ticket_category="Category where ticket channels are created (optional)",
        staff_role="Role that can see and manage all tickets (optional)",
        panel_text="Text shown on the ticket panel embed",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        transcript_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel = None,
        staff_role: discord.Role = None,
        panel_text: str = "Click the button below to open a support ticket.",
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Save config
        cfg_update = {
            "panel_channel_id":     panel_channel.id,
            "transcript_channel_id": transcript_channel.id,
            "panel_text":           panel_text,
        }
        if ticket_category:
            cfg_update["ticket_category_id"] = ticket_category.id
        if staff_role:
            cfg_update["staff_role_id"] = staff_role.id

        await _save_ticket_config(interaction.guild.id, cfg_update)

        # Send panel
        panel_embed = discord.Embed(
            title="🎟 Support Tickets",
            description=panel_text,
            color=0x5865F2,
        )
        panel_embed.set_footer(text="Click the button below to open a ticket.")

        try:
            await panel_channel.send(embed=panel_embed, view=TicketPanelView(self))
        except discord.Forbidden:
            await interaction.followup.send(
                embed=_err("Failed", f"I can't send messages in {panel_channel.mention}."),
                ephemeral=True,
            )
            return

        e = discord.Embed(title="✅ Ticket System Configured", color=0x2ECC71)
        e.add_field(name="Panel Channel",      value=panel_channel.mention,      inline=True)
        e.add_field(name="Transcript Channel", value=transcript_channel.mention, inline=True)
        e.add_field(name="Category",           value=ticket_category.mention if ticket_category else "None", inline=True)
        e.add_field(name="Staff Role",         value=staff_role.mention if staff_role else "None", inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /ticket_config ─────────────────────────────────────────────────────

    @app_commands.command(name="ticket_config", description="View current ticket system configuration.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ticket_config(self, interaction: discord.Interaction) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        cfg = await _get_ticket_config(interaction.guild.id)

        pc  = cfg.get("panel_channel_id")
        tc  = cfg.get("transcript_channel_id")
        cat = cfg.get("ticket_category_id")
        sr  = cfg.get("staff_role_id")
        count = cfg.get("ticket_count", 0)
        open_count = len(cfg.get("open_tickets", {}))

        e = discord.Embed(title="⚙️ Ticket System Config", color=0x3498DB)
        e.add_field(name="Panel Channel",      value=f"<#{pc}>"   if pc  else "❌ Not set", inline=True)
        e.add_field(name="Transcript Channel", value=f"<#{tc}>"   if tc  else "❌ Not set", inline=True)
        e.add_field(name="Category",           value=f"<#{cat}>"  if cat else "None",        inline=True)
        e.add_field(name="Staff Role",         value=f"<@&{sr}>"  if sr  else "None",        inline=True)
        e.add_field(name="Total Tickets",      value=str(count),                             inline=True)
        e.add_field(name="Open Tickets",       value=str(open_count),                        inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("TicketCog error: %s", error)
        msg = "❌ Something went wrong. Please try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
