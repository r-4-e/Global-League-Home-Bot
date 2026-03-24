"""
cogs/utility.py — Utility Commands for Elura.

Commands:
  /avatar     — view full-size avatar of any user
  /banner     — view full-size banner of any user
  /8ball      — magic 8 ball
  /poll       — create a button-based poll
  /afk        — set AFK status, auto-reply when mentioned
  /remind     — set a reminder, bot pings you after a duration
  /say        — make the bot say something in a channel
  /embed      — send a custom embed to a channel
  /ping       — check bot latency
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

# AFK store { guild_id: { user_id: reason } }
_afk_store: dict[int, dict[int, str]] = {}

# Reminders store [ {user_id, channel_id, message, fire_at} ]
_reminders: list[dict] = []


def _parse_duration(duration: str) -> int | None:
    """Parse duration string like 10s, 5m, 2h, 1d into seconds."""
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if not duration:
        return None
    unit = duration[-1].lower()
    if unit not in unit_map:
        return None
    try:
        amount = int(duration[:-1])
        return amount * unit_map[unit]
    except ValueError:
        return None


def _ok(t, d=""):   return discord.Embed(title=f"✅ {t}", description=d, color=0x2ECC71)
def _err(t, d=""):  return discord.Embed(title=f"❌ {t}", description=d, color=0xE74C3C)
def _info(t, d=""): return discord.Embed(title=f"ℹ️ {t}", description=d, color=0x3498DB)


# ---------------------------------------------------------------------------
# Poll View
# ---------------------------------------------------------------------------

class PollView(discord.ui.View):
    def __init__(self, options: list[str], question: str) -> None:
        super().__init__(timeout=86400)  # 24 hours
        self.question = question
        self.options  = options
        self.votes:   dict[str, set[int]] = {opt: set() for opt in options}
        self._add_buttons()

    def _add_buttons(self) -> None:
        colors = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.danger,
            discord.ButtonStyle.secondary,
        ]
        for i, opt in enumerate(self.options[:4]):
            self.add_item(PollButton(opt, colors[i % len(colors)]))

    def build_embed(self) -> discord.Embed:
        total = sum(len(v) for v in self.votes.values())
        e = discord.Embed(title=f"📊 {self.question}", color=0x3498DB)
        for opt, voters in self.votes.items():
            count = len(voters)
            pct   = int((count / total * 100)) if total > 0 else 0
            bar   = "█" * (pct // 10) + "░" * (10 - pct // 10)
            e.add_field(
                name=opt,
                value=f"`{bar}` {pct}% ({count} votes)",
                inline=False,
            )
        e.set_footer(text=f"Total votes: {total}  •  Poll closes in 24 hours")
        return e


class PollButton(discord.ui.Button):
    def __init__(self, option: str, style: discord.ButtonStyle) -> None:
        super().__init__(label=option, style=style)
        self.option = option

    async def callback(self, interaction: discord.Interaction) -> None:
        view: PollView = self.view  # type: ignore[assignment]
        uid = interaction.user.id

        # Remove previous vote
        for opt, voters in view.votes.items():
            voters.discard(uid)

        # Add new vote
        view.votes[self.option].add(uid)

        await interaction.response.edit_message(embed=view.build_embed(), view=view)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class UtilityCog(commands.Cog, name="Utility"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /ping ─────────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="Check the bot's latency.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = round(self.bot.latency * 1000)
        color   = 0x2ECC71 if latency < 100 else (0xF39C12 if latency < 200 else 0xE74C3C)
        e = discord.Embed(title="🏓 Pong!", color=color)
        e.add_field(name="Latency", value=f"**{latency}ms**", inline=True)
        e.add_field(name="Status",  value="🟢 Good" if latency < 100 else ("🟡 Okay" if latency < 200 else "🔴 High"), inline=True)
        await interaction.response.send_message(embed=e)

    # ── /avatar ───────────────────────────────────────────────────────────

    @app_commands.command(name="avatar", description="View a user's full-size avatar.")
    @app_commands.describe(
        user="User to view (default: yourself)",
        avatar_type="Server avatar or global avatar",
    )
    @app_commands.choices(avatar_type=[
        app_commands.Choice(name="Server avatar (if set)", value="server"),
        app_commands.Choice(name="Global avatar",          value="global"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def avatar(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        avatar_type: str = "server",
    ) -> None:
        target = user or interaction.user

        if avatar_type == "server" and isinstance(target, discord.Member) and target.guild_avatar:
            av  = target.guild_avatar
            tag = "Server Avatar"
        else:
            av  = target.avatar or target.default_avatar
            tag = "Global Avatar"

        formats = []
        if av.is_animated():
            formats.append(f"[GIF]({av.with_format('gif').url})")
        formats.append(f"[PNG]({av.with_format('png').url})")
        formats.append(f"[JPG]({av.with_format('jpg').url})")
        formats.append(f"[WEBP]({av.with_format('webp').url})")

        e = discord.Embed(
            title=f"🖼️ {target.display_name}'s {tag}",
            description=" • ".join(formats),
            color=0x5865F2,
        )
        e.set_image(url=av.with_size(1024).url)
        e.set_footer(text=f"User ID: {target.id}")
        await interaction.response.send_message(embed=e)

    # ── /banner ───────────────────────────────────────────────────────────

    @app_commands.command(name="banner", description="View a user's profile banner.")
    @app_commands.describe(user="User to view (default: yourself)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def banner(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        target = user or interaction.user
        await interaction.response.defer()

        # Must fetch user to get banner
        fetched = await self.bot.fetch_user(target.id)
        if not fetched.banner:
            await interaction.followup.send(
                embed=_err("No Banner", f"**{target.display_name}** doesn't have a profile banner."),
                ephemeral=True,
            )
            return

        banner = fetched.banner
        formats = []
        if banner.is_animated():
            formats.append(f"[GIF]({banner.with_format('gif').url})")
        formats.append(f"[PNG]({banner.with_format('png').url})")
        formats.append(f"[WEBP]({banner.with_format('webp').url})")

        e = discord.Embed(
            title=f"🖼️ {target.display_name}'s Banner",
            description=" • ".join(formats),
            color=0x5865F2,
        )
        e.set_image(url=banner.with_size(1024).url)
        await interaction.followup.send(embed=e)

    # ── /8ball ────────────────────────────────────────────────────────────

    @app_commands.command(name="8ball", description="Ask the magic 8 ball a question.")
    @app_commands.describe(question="Your yes/no question")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def eightball(self, interaction: discord.Interaction, question: str) -> None:
        responses = [
            # Positive
            ("🟢", "It is certain."),
            ("🟢", "Without a doubt."),
            ("🟢", "Yes, definitely."),
            ("🟢", "You may rely on it."),
            ("🟢", "As I see it, yes."),
            ("🟢", "Most likely."),
            ("🟢", "Signs point to yes."),
            ("🟢", "Outlook good."),
            # Neutral
            ("🟡", "Reply hazy, try again."),
            ("🟡", "Ask again later."),
            ("🟡", "Better not tell you now."),
            ("🟡", "Cannot predict now."),
            ("🟡", "Concentrate and ask again."),
            # Negative
            ("🔴", "Don't count on it."),
            ("🔴", "My reply is no."),
            ("🔴", "My sources say no."),
            ("🔴", "Outlook not so good."),
            ("🔴", "Very doubtful."),
        ]
        dot, answer = random.choice(responses)
        e = discord.Embed(title="🎱 Magic 8 Ball", color=0x2C3E50)
        e.add_field(name="❓ Question", value=question,        inline=False)
        e.add_field(name=f"{dot} Answer",  value=f"*{answer}*", inline=False)
        await interaction.response.send_message(embed=e)

    # ── /poll ─────────────────────────────────────────────────────────────

    @app_commands.command(name="poll", description="Create an interactive poll with up to 4 options.")
    @app_commands.describe(
        question="The poll question",
        option1="First option",
        option2="Second option",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
    ) -> None:
        options = [o for o in [option1, option2, option3, option4] if o]
        view    = PollView(options, question)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    # ── /afk ──────────────────────────────────────────────────────────────

    @app_commands.command(name="afk", description="Set your AFK status. Bot will auto-reply when you're mentioned.")
    @app_commands.describe(reason="Reason for being AFK (default: AFK)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        guild_id = interaction.guild.id
        if guild_id not in _afk_store:
            _afk_store[guild_id] = {}
        _afk_store[guild_id][interaction.user.id] = reason

        e = discord.Embed(
            title="💤 AFK Set",
            description=f"You are now AFK: **{reason}**\nI'll let people know when they mention you.",
            color=0x95A5A6,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        guild_id  = message.guild.id
        guild_afk = _afk_store.get(guild_id, {})

        # Remove AFK if the AFK user sends a message
        if message.author.id in guild_afk:
            del guild_afk[message.author.id]
            try:
                await message.reply(
                    embed=discord.Embed(
                        description="✅ Welcome back! Your AFK status has been removed.",
                        color=0x2ECC71,
                    ),
                    delete_after=5,
                )
            except discord.Forbidden:
                pass
            return

        # Notify if a mentioned user is AFK
        for mentioned in message.mentions:
            if mentioned.id in guild_afk:
                reason = guild_afk[mentioned.id]
                try:
                    await message.reply(
                        embed=discord.Embed(
                            description=f"💤 **{mentioned.display_name}** is AFK: {reason}",
                            color=0x95A5A6,
                        ),
                        delete_after=8,
                    )
                except discord.Forbidden:
                    pass

    # ── /remind ───────────────────────────────────────────────────────────

    @app_commands.command(name="remind", description="Set a reminder. Bot pings you when time's up.")
    @app_commands.describe(
        duration="Duration e.g. 10m, 2h, 1d",
        message="What to remind you about",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def remind(
        self,
        interaction: discord.Interaction,
        duration: str,
        message: str,
    ) -> None:
        seconds = _parse_duration(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(
                embed=_err("Invalid Duration", "Use formats like `10s`, `5m`, `2h`, `1d`."),
                ephemeral=True,
            )
            return
        if seconds > 86400 * 7:
            await interaction.response.send_message(
                embed=_err("Too Long", "Maximum reminder duration is 7 days."),
                ephemeral=True,
            )
            return

        fire_at = datetime.now(timezone.utc).timestamp() + seconds

        e = discord.Embed(
            title="⏰ Reminder Set",
            description=f"I'll remind you in **{duration}**.\n\n> {message}",
            color=0x3498DB,
        )
        e.set_footer(text=f"Reminder fires at {datetime.fromtimestamp(fire_at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        await interaction.response.send_message(embed=e, ephemeral=True)

        # Fire reminder after delay
        asyncio.create_task(
            self._fire_reminder(
                user_id=interaction.user.id,
                channel_id=interaction.channel.id,
                message=message,
                seconds=seconds,
            )
        )

    async def _fire_reminder(
        self,
        user_id: int,
        channel_id: int,
        message: str,
        seconds: int,
    ) -> None:
        await asyncio.sleep(seconds)
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            e = discord.Embed(
                title="⏰ Reminder!",
                description=message,
                color=0xF39C12,
            )
            e.set_footer(text="You asked me to remind you about this.")
            await channel.send(content=f"<@{user_id}>", embed=e)
        except discord.Forbidden:
            pass

    # ── /say ─────────────────────────────────────────────────────────────

    @app_commands.command(name="say", description="[Admin] Make the bot send a message in a channel.")
    @app_commands.describe(
        channel="Channel to send the message in",
        message="Message content",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def say(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return
        try:
            await channel.send(message)
            await interaction.response.send_message(
                embed=_ok("Message Sent", f"Sent to {channel.mention}."), ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=_err("Failed", f"I can't send messages in {channel.mention}."), ephemeral=True
            )

    # ── /embed ────────────────────────────────────────────────────────────

    @app_commands.command(name="embed", description="[Admin] Send a custom embed to a channel.")
    @app_commands.describe(
        channel="Channel to send the embed in",
        title="Embed title",
        description="Embed description",
        color="Hex color e.g. #FF5733 (optional)",
        image_url="Image URL to attach (optional)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def embed_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        description: str,
        color: str = "#5865F2",
        image_url: str | None = None,
    ) -> None:
        ok, msg = check_invoker_permission(interaction, "administrator")
        if not ok:
            await interaction.response.send_message(embed=_err("Permission Denied", msg), ephemeral=True)
            return

        try:
            hex_color = int(color.strip("#"), 16)
        except ValueError:
            hex_color = 0x5865F2

        e = discord.Embed(title=title, description=description, color=hex_color)
        e.timestamp = datetime.now(timezone.utc)
        if image_url:
            e.set_image(url=image_url)

        try:
            await channel.send(embed=e)
            await interaction.response.send_message(
                embed=_ok("Embed Sent", f"Sent to {channel.mention}."), ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=_err("Failed", f"I can't send messages in {channel.mention}."), ephemeral=True
            )

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("UtilityCog error: %s", error)
        msg = "❌ Something went wrong. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
