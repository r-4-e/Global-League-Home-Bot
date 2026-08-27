"""
cogs/suggestions.py — GL Suggestion System

Members submit suggestions via gl.suggest <idea>.
Staff review them in a private log channel with Accept/Deny buttons.
The original suggestion embed updates with the verdict.

Channels:
    Public suggestions : 1542626257974460537
    Staff review log  : 1542626319886721071
    Staff review role : 1515970181782966382
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config
from database import db

log = logging.getLogger("elura.suggestions")

SUGGESTION_CHANNEL_ID = 1542626257974460537
LOG_CHANNEL_ID        = 1542626319886721071
REVIEWER_ROLE_ID      = 1515970181782966382

STATUS_COLORS = {
    "pending":  0x3498DB,   # blue
    "accepted": 0x2ECC71,   # green
    "denied":   0xE74C3C,   # red
}

STATUS_EMOJI = {
    "pending":  "🟡",
    "accepted": "✅",
    "denied":   "❌",
}


def _is_reviewer(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == REVIEWER_ROLE_ID for r in member.roles)


def _suggestion_embed(
    author: discord.Member | discord.User,
    idea: str,
    suggestion_id: int,
    status: str = "pending",
    reviewer: discord.Member | None = None,
    reason: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        description=f"**{idea}**",
        color=STATUS_COLORS[status],
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(
        name=f"{author.display_name} suggests…",
        icon_url=author.display_avatar.url,
    )
    embed.set_footer(text=f"Suggestion #{suggestion_id} • {STATUS_EMOJI[status]} {status.capitalize()}")

    if status != "pending" and reviewer:
        embed.add_field(
            name=f"{STATUS_EMOJI[status]} {'Accepted' if status == 'accepted' else 'Denied'} by",
            value=reviewer.mention,
            inline=True,
        )
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)

    return embed


class DenyReasonModal(discord.ui.Modal, title="Denial Reason (Optional)"):
    reason = discord.ui.TextInput(
        label="Reason for denial",
        placeholder="Leave blank to deny without a reason…",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, cog: "Suggestions", suggestion_id: int):
        super().__init__()
        self.cog = cog
        self.suggestion_id = suggestion_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self.cog.process_verdict(
            interaction=interaction,
            suggestion_id=self.suggestion_id,
            status="denied",
            reviewer=interaction.user,
            reason=self.reason.value.strip() or None,
        )


class SuggestionReviewView(discord.ui.View):
    def __init__(self, cog: "Suggestions", suggestion_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.suggestion_id = suggestion_id

    @discord.ui.button(
        label="Accept",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="suggestion:accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not _is_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to review suggestions.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self.cog.process_verdict(
            interaction=interaction,
            suggestion_id=self.suggestion_id,
            status="accepted",
            reviewer=interaction.user,
            reason=None,
        )

    @discord.ui.button(
        label="Deny",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="suggestion:deny",
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not _is_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to review suggestions.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            DenyReasonModal(self.cog, self.suggestion_id)
        )


class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # suggestion_id -> {"public_msg_id": int, "log_msg_id": int, "author_id": int, "idea": str}
        self._cache: dict[int, dict] = {}
        self._counter: int = 0

    async def cog_load(self) -> None:
        self.bot.add_view(SuggestionReviewView(self, 0))
        await self._load_counter()

    async def _load_counter(self) -> None:
        """Load suggestion counter from DB so IDs persist across restarts."""
        try:
            cfg = await db.get_guild_config(config.GUILD_ID)
            self._counter = (cfg or {}).get("suggestion_counter", 0)
        except Exception:
            self._counter = 0

    async def _save_counter(self) -> None:
        try:
            await db.upsert_guild_config({
                "guild_id": config.GUILD_ID,
                "suggestion_counter": self._counter,
            })
        except Exception as exc:
            log.warning("Could not save suggestion counter: %s", exc)

    async def process_verdict(
        self,
        interaction: discord.Interaction,
        suggestion_id: int,
        status: str,
        reviewer: discord.Member,
        reason: str | None,
    ) -> None:
        data = self._cache.get(suggestion_id)
        if data is None:
            await interaction.followup.send(
                "❌ Suggestion not found in cache. It may have been reviewed already or the bot restarted.",
                ephemeral=True,
            )
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        author = guild.get_member(data["author_id"]) or await self.bot.fetch_user(data["author_id"])

        # Update public suggestion embed
        pub_channel = self.bot.get_channel(SUGGESTION_CHANNEL_ID)
        if pub_channel:
            try:
                pub_msg = await pub_channel.fetch_message(data["public_msg_id"])
                updated_embed = _suggestion_embed(
                    author=author,
                    idea=data["idea"],
                    suggestion_id=suggestion_id,
                    status=status,
                    reviewer=reviewer,
                    reason=reason,
                )
                await pub_msg.edit(embed=updated_embed)
            except (discord.NotFound, discord.Forbidden) as exc:
                log.warning("Could not update public suggestion message: %s", exc)

        # Update log embed + disable buttons
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                log_msg = await log_channel.fetch_message(data["log_msg_id"])
                updated_log_embed = discord.Embed(
                    description=f"**{data['idea']}**",
                    color=STATUS_COLORS[status],
                    timestamp=datetime.now(timezone.utc),
                )
                updated_log_embed.set_author(
                    name=f"Suggestion #{suggestion_id} by {author.display_name}",
                    icon_url=author.display_avatar.url,
                )
                updated_log_embed.add_field(
                    name=f"{STATUS_EMOJI[status]} {'Accepted' if status == 'accepted' else 'Denied'} by",
                    value=reviewer.mention,
                    inline=True,
                )
                if reason:
                    updated_log_embed.add_field(name="Reason", value=reason, inline=False)
                updated_log_embed.set_footer(text=f"Suggestion #{suggestion_id} • {status.capitalize()}")

                disabled_view = discord.ui.View()
                accept_btn = discord.ui.Button(
                    label="Accept", style=discord.ButtonStyle.success,
                    emoji="✅", disabled=True,
                )
                deny_btn = discord.ui.Button(
                    label="Deny", style=discord.ButtonStyle.danger,
                    emoji="❌", disabled=True,
                )
                disabled_view.add_item(accept_btn)
                disabled_view.add_item(deny_btn)

                await log_msg.edit(embed=updated_log_embed, view=disabled_view)
            except (discord.NotFound, discord.Forbidden) as exc:
                log.warning("Could not update log message: %s", exc)

        # DM the author
        verdict_word = "accepted" if status == "accepted" else "denied"
        try:
            dm_embed = discord.Embed(
                title=f"{STATUS_EMOJI[status]} Your suggestion was {verdict_word}!",
                description=f"**Your idea:** {data['idea']}",
                color=STATUS_COLORS[status],
                timestamp=datetime.now(timezone.utc),
            )
            if reason:
                dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"Suggestion #{suggestion_id} • GL Server")
            await author.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # DMs closed

        # Remove from cache
        self._cache.pop(suggestion_id, None)

        await interaction.followup.send(
            f"✅ Suggestion #{suggestion_id} marked as **{status}**.", ephemeral=True
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.command(name="suggest")
    @commands.guild_only()
    @commands.cooldown(1, 300, commands.BucketType.user)  # 1 suggestion per 5 minutes
    async def suggest(self, ctx: commands.Context, *, idea: str) -> None:
        """Submit a suggestion. Usage: gl.suggest <your idea>"""
        if len(idea) < 10:
            await ctx.send("❌ Suggestion too short — give us more detail (min 10 characters).")
            return
        if len(idea) > 1000:
            await ctx.send("❌ Suggestion too long (max 1000 characters).")
            return

        self._counter += 1
        suggestion_id = self._counter
        await self._save_counter()

        pub_channel = self.bot.get_channel(SUGGESTION_CHANNEL_ID)
        log_channel  = self.bot.get_channel(LOG_CHANNEL_ID)

        if pub_channel is None or log_channel is None:
            await ctx.send("❌ Suggestion channels not found. Contact an admin.")
            self._counter -= 1
            return

        # Post to public suggestions channel
        pub_embed = _suggestion_embed(
            author=ctx.author,
            idea=idea,
            suggestion_id=suggestion_id,
            status="pending",
        )
        try:
            pub_msg = await pub_channel.send(embed=pub_embed)
            await pub_msg.add_reaction("👍")
            await pub_msg.add_reaction("👎")
        except discord.Forbidden:
            await ctx.send("❌ I can't post in the suggestions channel.")
            self._counter -= 1
            return

        # Post to staff log channel with review buttons
        log_embed = discord.Embed(
            description=f"**{idea}**",
            color=STATUS_COLORS["pending"],
            timestamp=datetime.now(timezone.utc),
        )
        log_embed.set_author(
            name=f"New Suggestion #{suggestion_id} by {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url,
        )
        log_embed.add_field(name="Author", value=ctx.author.mention, inline=True)
        log_embed.add_field(name="User ID", value=str(ctx.author.id), inline=True)
        log_embed.set_footer(text=f"Suggestion #{suggestion_id} • Pending review")

        view = SuggestionReviewView(self, suggestion_id)
        try:
            log_msg = await log_channel.send(
                content=f"<@&{REVIEWER_ROLE_ID}>",
                embed=log_embed,
                view=view,
            )
        except discord.Forbidden:
            await ctx.send("❌ I can't post in the staff review channel.")
            await pub_msg.delete()
            self._counter -= 1
            return

        # Cache for verdict processing
        self._cache[suggestion_id] = {
            "public_msg_id": pub_msg.id,
            "log_msg_id":    log_msg.id,
            "author_id":     ctx.author.id,
            "idea":          idea,
        }

        # Confirm to user ephemerally
        await ctx.message.delete()
        confirm = await ctx.send(
            embed=discord.Embed(
                title="✅ Suggestion Submitted!",
                description=f"Your suggestion has been posted in <#{SUGGESTION_CHANNEL_ID}> for the community to vote on and staff to review.",
                color=0x2ECC71,
            ),
            delete_after=10,
        )

    @suggest.error
    async def suggest_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            minutes = int(error.retry_after // 60)
            seconds = int(error.retry_after % 60)
            time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
            await ctx.send(
                f"⏳ You can submit another suggestion in **{time_str}**.",
                delete_after=10,
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "❌ You need to include your idea.\n"
                "Usage: `gl.suggest <your idea>`",
                delete_after=10,
            )

    @commands.command(name="suggestion_config")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def suggestion_config(self, ctx: commands.Context) -> None:
        """View suggestion system config."""
        pub_ch  = self.bot.get_channel(SUGGESTION_CHANNEL_ID)
        log_ch  = self.bot.get_channel(LOG_CHANNEL_ID)
        role    = ctx.guild.get_role(REVIEWER_ROLE_ID)
        pending = len(self._cache)

        embed = discord.Embed(title="💡 Suggestion System Config", color=0x3498DB)
        embed.add_field(name="Public Channel",  value=pub_ch.mention if pub_ch else "❌ Not found",  inline=True)
        embed.add_field(name="Review Channel",  value=log_ch.mention if log_ch else "❌ Not found",  inline=True)
        embed.add_field(name="Reviewer Role",   value=role.mention if role else "❌ Not found",       inline=True)
        embed.add_field(name="Total Submitted", value=str(self._counter),                             inline=True)
        embed.add_field(name="Pending Review",  value=str(pending),                                   inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))
