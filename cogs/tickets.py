"""
cogs/tickets.py — Ticket system. Prefix: gl.
"""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils.permissions import check_invoker_permission, _member_tier

log = logging.getLogger(__name__)
RULE_TYPE = "tickets"


async def _get_ticket_config(guild_id):
    rules = await db.get_automod_rules(guild_id)
    for r in rules:
        if r.get("rule_type") == RULE_TYPE:
            return r.get("config") or {}
    return {}


async def _save_ticket_config(guild_id, update):
    existing = await _get_ticket_config(guild_id)
    existing.update(update)
    await db.upsert_automod_rule(RULE_TYPE, True, existing, guild_id)


def _ok(t, d=""): return discord.Embed(title=f"✅ {t}", description=d, color=0x2ECC71)
def _err(t, d=""): return discord.Embed(title=f"❌ {t}", description=d, color=0xE74C3C)


def _is_staff(member: discord.Member) -> bool:
    """Returns True if member has any GL staff tier (Tier 1+) or is admin."""
    if member.guild_permissions.administrator:
        return True
    return _member_tier(member) >= 1


class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🎟 Open a Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketReasonModal(self.cog))


class TicketReasonModal(discord.ui.Modal, title="Open a Ticket"):
    reason = discord.ui.TextInput(
        label="Reason / Topic",
        placeholder="Describe your issue…",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=500,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_ticket(interaction, self.reason.value)


class TicketControlView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow ticket owner or any staff to close
        config = await _get_ticket_config(interaction.guild.id)
        open_tickets = config.get("open_tickets", {})
        owner_id = next(
            (uid for uid, ch_id in open_tickets.items() if ch_id == interaction.channel.id),
            None,
        )
        is_owner = owner_id and str(interaction.user.id) == str(owner_id)
        if not is_owner and not _is_staff(interaction.user):
            await interaction.response.send_message(
                embed=_err("No Permission", "Only the ticket owner or staff can close this ticket."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.close_ticket_from_button(interaction)

    @discord.ui.button(
        label="🙋 Claim Ticket",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:claim",
    )
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message(
                embed=_err("No Permission", "Only staff can claim tickets."),
                ephemeral=True,
            )
            return

        channel = interaction.channel
        guild   = interaction.guild
        claimer = interaction.user

        # Get ticket owner
        config = await _get_ticket_config(guild.id)
        open_tickets = config.get("open_tickets", {})
        owner_id = next(
            (uid for uid, ch_id in open_tickets.items() if ch_id == channel.id),
            None,
        )

        # Get staff role
        staff_role_id = config.get("staff_role_id")
        staff_role    = guild.get_role(int(staff_role_id)) if staff_role_id else None

        # Build new permission overwrites:
        # - @everyone: no access (unchanged)
        # - Bot: full access (unchanged)
        # - Ticket owner: read + send (unchanged)
        # - Staff role: read only (no send_messages) — locked out
        # - Claimer: read + send (explicitly granted)
        try:
            overwrites = dict(channel.overwrites)

            # Lock staff role to read-only
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )

            # Explicitly grant claimer send access
            overwrites[claimer] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

            # Restore ticket owner send access in case it got caught by role overwrite
            if owner_id:
                owner = guild.get_member(int(owner_id))
                if owner:
                    overwrites[owner] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    )

            await channel.edit(
                overwrites=overwrites,
                topic=f"📌 Claimed by {claimer} ({claimer.id})",
                reason=f"Ticket claimed by {claimer}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=_err("Failed", "I don't have permission to edit this channel."),
                ephemeral=True,
            )
            return

        # Store claimer in config so unclaim can restore
        open_tickets_meta = config.get("claimed_tickets", {})
        open_tickets_meta[str(channel.id)] = str(claimer.id)
        await _save_ticket_config(guild.id, {"claimed_tickets": open_tickets_meta})

        e = discord.Embed(
            title="🙋 Ticket Claimed",
            description=(
                f"{claimer.mention} has claimed this ticket.\n\n"
                f"Only {claimer.mention} and the ticket owner can send messages.\n"
                f"Other staff can still read but not respond."
            ),
            color=0x3498DB,
        )
        e.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=e)

    @discord.ui.button(
        label="📄 Transcript",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:transcript",
    )
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message(
                embed=_err("No Permission", "Only staff can save transcripts."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        transcript = await TicketCog._generate_transcript_static(
            interaction.channel, interaction.guild, None
        )
        file = discord.File(
            io.BytesIO(transcript.encode()),
            filename=f"{interaction.channel.name}-transcript.txt",
        )
        await interaction.followup.send(
            embed=_ok("Transcript Ready", "Here's the transcript."),
            file=file,
            ephemeral=True,
        )


class TicketCog(commands.Cog, name="Tickets"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketControlView(self))

    async def create_ticket(self, interaction, reason):
        guild = interaction.guild
        member = interaction.user
        config = await _get_ticket_config(guild.id)

        # Check for existing open ticket
        open_tickets = config.get("open_tickets", {})
        if str(member.id) in open_tickets:
            existing_ch = guild.get_channel(open_tickets[str(member.id)])
            if existing_ch:
                await interaction.followup.send(
                    embed=_err(
                        "Already Open",
                        f"You already have an open ticket: {existing_ch.mention}\n"
                        "Close it before opening a new one.",
                    ),
                    ephemeral=True,
                )
                return

        category_id   = config.get("ticket_category_id")
        staff_role_id = config.get("staff_role_id")
        ticket_count  = config.get("ticket_count", 0) + 1

        category = guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                manage_channels=True, manage_messages=True,
                read_message_history=True,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True,
            ),
        }
        if staff_role_id:
            sr = guild.get_role(int(staff_role_id))
            if sr:
                overwrites[sr] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True, manage_messages=True,
                )

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
                embed=_err("Failed", "I can't create channels. Check my permissions."),
                ephemeral=True,
            )
            return

        open_tickets[str(member.id)] = channel.id
        await _save_ticket_config(guild.id, {
            "open_tickets": open_tickets,
            "ticket_count": ticket_count,
        })

        panel_embed = discord.Embed(
            title=f"🎟 Ticket #{ticket_count:04d}",
            description=(
                f"**Opened by:** {member.mention}\n"
                f"**Reason:** {reason}\n\n"
                "Staff will be with you shortly.\n"
                "Click **🔒 Close Ticket** when your issue is resolved."
            ),
            color=0x5865F2,
        )
        panel_embed.set_thumbnail(url=member.display_avatar.url)
        panel_embed.timestamp = datetime.now(timezone.utc)

        await channel.send(
            content=f"{member.mention}" + (f" | <@&{staff_role_id}>" if staff_role_id else ""),
            embed=panel_embed,
            view=TicketControlView(self),
        )
        await interaction.followup.send(
            embed=_ok("Ticket Opened", f"Your ticket: {channel.mention}"),
            ephemeral=True,
        )

    async def close_ticket_from_button(self, interaction):
        channel = interaction.channel
        guild   = interaction.guild
        config  = await _get_ticket_config(guild.id)
        open_tickets = config.get("open_tickets", {})

        owner_id = next(
            (uid for uid, ch_id in open_tickets.items() if ch_id == channel.id),
            None,
        )
        if owner_id is None:
            await interaction.followup.send(
                embed=_err("Not a Ticket", "This isn't a managed ticket channel."),
                ephemeral=True,
            )
            return

        transcript = await self._generate_transcript_static(channel, guild, owner_id)

        # Save transcript
        transcript_ch_id = config.get("transcript_channel_id")
        if transcript_ch_id:
            transcript_ch = guild.get_channel(int(transcript_ch_id))
            if isinstance(transcript_ch, discord.TextChannel):
                t_embed = discord.Embed(
                    title=f"📄 Transcript — {channel.name}",
                    description=(
                        f"**Opened by:** <@{owner_id}>\n"
                        f"**Closed by:** {interaction.user.mention}"
                    ),
                    color=0x95A5A6,
                )
                t_embed.timestamp = datetime.now(timezone.utc)
                file = discord.File(
                    io.BytesIO(transcript.encode()),
                    filename=f"{channel.name}-transcript.txt",
                )
                try:
                    await transcript_ch.send(embed=t_embed, file=file)
                except discord.Forbidden:
                    pass

        open_tickets.pop(str(owner_id), None)
        await _save_ticket_config(guild.id, {"open_tickets": open_tickets})

        await channel.send(
            embed=discord.Embed(
                title="🔒 Ticket Closed",
                description=f"Closed by {interaction.user.mention}. Deleting in 5 seconds.",
                color=0xE74C3C,
            )
        )
        await interaction.followup.send(
            embed=_ok("Closed", "Ticket closed and transcript saved."),
            ephemeral=True,
        )
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.Forbidden:
            pass

    @staticmethod
    async def _generate_transcript_static(channel, guild, owner_id):
        lines = [
            "TICKET TRANSCRIPT",
            f"Channel: #{channel.name}",
            f"Server: {guild.name}",
            f"Opened by: {owner_id or 'Unknown'}",
            f"Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
        ]
        try:
            async for msg in channel.history(limit=500, oldest_first=True):
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                content = msg.content or "[embed/attachment]"
                lines.append(f"[{ts}] {msg.author}: {content}")
        except discord.Forbidden:
            lines.append("[Could not fetch message history]")
        return "\n".join(lines)

    # ── Commands ──────────────────────────────────────────────────────────────
    @commands.command(name="ticket_setup")
    @commands.guild_only()
    async def ticket_setup(
        self,
        ctx,
        panel_channel: discord.TextChannel,
        transcript_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel = None,
        staff_role: discord.Role = None,
        *,
        panel_text: str = "Click the button below to open a support ticket.",
    ):
        """Setup ticket system. Usage: gl.ticket_setup #panel #transcripts [category] [staff_role]"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok:
            await ctx.send(msg)
            return

        async with ctx.typing():
            cfg_update = {
                "panel_channel_id":      panel_channel.id,
                "transcript_channel_id": transcript_channel.id,
                "panel_text":            panel_text,
            }
            if ticket_category:
                cfg_update["ticket_category_id"] = ticket_category.id
            if staff_role:
                cfg_update["staff_role_id"] = staff_role.id

            await _save_ticket_config(ctx.guild.id, cfg_update)

            panel_embed = discord.Embed(
                title="🎟 Support Tickets",
                description=panel_text,
                color=0x5865F2,
            )
            panel_embed.set_footer(text="Click the button below to open a ticket.")
            try:
                await panel_channel.send(embed=panel_embed, view=TicketPanelView(self))
            except discord.Forbidden:
                await ctx.send(embed=_err("Failed", f"Can't send in {panel_channel.mention}."))
                return

        e = discord.Embed(title="✅ Ticket System Configured", color=0x2ECC71)
        e.add_field(name="Panel Channel",      value=panel_channel.mention,      inline=True)
        e.add_field(name="Transcript Channel", value=transcript_channel.mention, inline=True)
        e.add_field(name="Category",           value=ticket_category.mention if ticket_category else "None", inline=True)
        e.add_field(name="Staff Role",         value=staff_role.mention if staff_role else "None", inline=True)
        await ctx.send(embed=e)

    @commands.command(name="ticket_config")
    @commands.guild_only()
    async def ticket_config(self, ctx):
        """View ticket config."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok:
            await ctx.send(msg)
            return

        cfg = await _get_ticket_config(ctx.guild.id)
        pc  = cfg.get("panel_channel_id")
        tc  = cfg.get("transcript_channel_id")
        cat = cfg.get("ticket_category_id")
        sr  = cfg.get("staff_role_id")
        count      = cfg.get("ticket_count", 0)
        open_count = len(cfg.get("open_tickets", {}))

        e = discord.Embed(title="⚙️ Ticket Config", color=0x3498DB)
        e.add_field(name="Panel Channel",      value=f"<#{pc}>"  if pc  else "❌ Not set", inline=True)
        e.add_field(name="Transcript Channel", value=f"<#{tc}>"  if tc  else "❌ Not set", inline=True)
        e.add_field(name="Category",           value=f"<#{cat}>" if cat else "None",        inline=True)
        e.add_field(name="Staff Role",         value=f"<@&{sr}>" if sr  else "None",        inline=True)
        e.add_field(name="Total Tickets",      value=str(count),                            inline=True)
        e.add_field(name="Open Tickets",       value=str(open_count),                       inline=True)
        await ctx.send(embed=e)

    @commands.command(name="ticket_close")
    @commands.guild_only()
    async def ticket_close(self, ctx, channel: discord.TextChannel = None):
        """Force-close a ticket channel. Staff only. Usage: gl.ticket_close [#channel]"""
        if not _is_staff(ctx.author):
            await ctx.send(embed=_err("No Permission", "Only staff can force-close tickets."))
            return

        target = channel or ctx.channel
        config = await _get_ticket_config(ctx.guild.id)
        open_tickets = config.get("open_tickets", {})

        owner_id = next(
            (uid for uid, ch_id in open_tickets.items() if ch_id == target.id),
            None,
        )
        if owner_id is None:
            await ctx.send(embed=_err("Not a Ticket", f"{target.mention} isn't a managed ticket."))
            return

        transcript = await self._generate_transcript_static(target, ctx.guild, owner_id)
        transcript_ch_id = config.get("transcript_channel_id")
        if transcript_ch_id:
            transcript_ch = ctx.guild.get_channel(int(transcript_ch_id))
            if isinstance(transcript_ch, discord.TextChannel):
                t_embed = discord.Embed(
                    title=f"📄 Transcript — {target.name}",
                    description=f"**Opened by:** <@{owner_id}>\n**Force-closed by:** {ctx.author.mention}",
                    color=0x95A5A6,
                )
                t_embed.timestamp = datetime.now(timezone.utc)
                file = discord.File(
                    io.BytesIO(transcript.encode()),
                    filename=f"{target.name}-transcript.txt",
                )
                try:
                    await transcript_ch.send(embed=t_embed, file=file)
                except discord.Forbidden:
                    pass

        open_tickets.pop(str(owner_id), None)
        await _save_ticket_config(ctx.guild.id, {"open_tickets": open_tickets})
        await ctx.send(embed=_ok("Ticket Force-Closed", f"Transcript saved. Deleting {target.mention} in 5s."))
        await asyncio.sleep(5)
        try:
            await target.delete(reason=f"Force-closed by {ctx.author}")
        except discord.Forbidden:
            await ctx.send(embed=_err("Failed", "I can't delete that channel."))

    @commands.command(name="ticket_list")
    @commands.guild_only()
    async def ticket_list(self, ctx):
        """List all currently open tickets. Staff only."""
        if not _is_staff(ctx.author):
            await ctx.send(embed=_err("No Permission", "Only staff can view the ticket list."))
            return

        config = await _get_ticket_config(ctx.guild.id)
        open_tickets = config.get("open_tickets", {})

        if not open_tickets:
            await ctx.send(embed=_ok("No Open Tickets", "There are no open tickets right now."))
            return

        e = discord.Embed(
            title=f"🎟 Open Tickets ({len(open_tickets)})",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        for uid, ch_id in open_tickets.items():
            ch = ctx.guild.get_channel(ch_id)
            ch_mention = ch.mention if ch else f"Deleted channel ({ch_id})"
            e.add_field(name=f"<@{uid}>", value=ch_mention, inline=True)

        await ctx.send(embed=e)


    @commands.command(name="ticket_unclaim")
    @commands.guild_only()
    async def ticket_unclaim(self, ctx, channel: discord.TextChannel = None):
        """Unclaim a ticket — restores staff send access. Claimer or admin only."""
        target = channel or ctx.channel
        config = await _get_ticket_config(ctx.guild.id)
        claimed_tickets = config.get("claimed_tickets", {})
        claimer_id = claimed_tickets.get(str(target.id))

        if not claimer_id:
            await ctx.send(embed=_err("Not Claimed", "This ticket hasn't been claimed."))
            return

        is_claimer = str(ctx.author.id) == str(claimer_id)
        if not is_claimer and not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=_err("No Permission", "Only the claimer or an admin can unclaim this ticket."))
            return

        staff_role_id = config.get("staff_role_id")
        staff_role    = ctx.guild.get_role(int(staff_role_id)) if staff_role_id else None

        try:
            overwrites = dict(target.overwrites)

            # Restore staff role send access
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                )

            # Remove claimer-specific overwrite
            claimer = ctx.guild.get_member(int(claimer_id))
            if claimer and claimer in overwrites:
                del overwrites[claimer]

            await target.edit(
                overwrites=overwrites,
                topic=target.topic.replace(f"📌 Claimed by ", "📋 ") if target.topic else None,
                reason=f"Ticket unclaimed by {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.send(embed=_err("Failed", "I can't edit this channel."))
            return

        claimed_tickets.pop(str(target.id), None)
        await _save_ticket_config(ctx.guild.id, {"claimed_tickets": claimed_tickets})

        await ctx.send(embed=discord.Embed(
            title="✅ Ticket Unclaimed",
            description=f"{target.mention} is now open for all staff to assist.",
            color=0x2ECC71,
        ))


async def setup(bot):
    await bot.add_cog(TicketCog(bot))
