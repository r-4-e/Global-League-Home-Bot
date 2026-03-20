"""
cogs/help_cog.py — Interactive /help panel for Elura.

Features:
  • Category dropdown (Moderation, AutoMod, Setup, Permissions, FAQ)
  • Dynamic embed updates
  • Pagination for large categories
  • Command usage examples
  • Usage stat tracking in DB
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from database import db
from utils import embeds as em

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Help content definitions
# ---------------------------------------------------------------------------

HELP_DATA: dict[str, dict] = {
    "moderation": {
        "title":       "🔨 Moderation Commands",
        "description": "Commands to manage members and keep the server safe.",
        "color":       0x9B59B6,
        "pages": [
            # Page 1 — member punishment
            [
                ("**/warn** `<user>` `[reason]`",        "Issue a warning to a member. Requires Warn Role."),
                ("**/unwarn** `<case_id>`",               "Remove a warning by its case ID. Requires Warn Role."),
                ("**/history** `<user>` `[page]`",        "View paginated moderation history for a user."),
                ("**/mute** `<user>` `[reason]` `[dur]`", "Apply muted role. Duration: `10m`, `2h`, `1d`."),
                ("**/unmute** `<user>` `[reason]`",       "Remove the muted role from a member."),
                ("**/timeout** `<user>` `[dur]` `[reason]`", "Discord timeout (max 28d). Duration: `10m`, `2h`."),
                ("**/untimeout** `<user>` `[reason]`",    "Remove an active timeout."),
                ("**/kick** `<user>` `[reason]`",         "Kick a member from the server."),
                ("**/ban** `<user>` `[reason]` `[del]`",  "Ban a member. Optionally delete 0–7 days of msgs."),
            ],
            # Page 2 — advanced
            [
                ("**/unban** `<user_id>` `[reason]`",     "Unban a user by their numeric ID."),
                ("**/softban** `<user>` `[reason]`",      "Ban + immediately unban to purge recent messages."),
                ("**/massban** `<ids>` `[reason]`",       "Ban multiple users. IDs separated by commas."),
                ("**/masskick** `<ids>` `[reason]`",      "Kick multiple members. IDs separated by commas."),
                ("**/clear** `<amount>` `[user]`",        "Bulk delete up to 100 messages; filter by user."),
                ("**/slowmode** `<secs>` `[channel]`",    "Set slowmode (0 = disable). Max 6 hours."),
                ("**/lock** `[channel]` `[reason]`",      "Prevent @everyone from sending in a channel."),
                ("**/unlock** `[channel]` `[reason]`",    "Re-allow @everyone to send in a channel."),
                ("**/nick** `<user>` `[nickname]`",       "Change or reset a member's nickname."),
                ("**/role_add** `<user>` `<role>`",       "Add a role to a member."),
                ("**/role_remove** `<user>` `<role>`",    "Remove a role from a member."),
            ],
        ],
    },
    "automod": {
        "title":       "🤖 AutoMod System",
        "description": "Automatic rule enforcement to keep your server clean.",
        "color":       0xF39C12,
        "pages": [
            [
                ("**Anti-Spam**",         f"Detects rapid message bursts. Auto-warns + short timeout."),
                ("**Anti-Duplicate**",    "Flags repeated identical messages sent in quick succession."),
                ("**Anti-Link**",         "Removes messages containing HTTP/HTTPS links (configurable)."),
                ("**Anti-Invite**",       "Removes Discord server invite links automatically."),
                ("**Anti-Caps**",         "Removes messages where >70 % of letters are uppercase."),
                ("**Mention Spam**",      "Warns and times out members who @mention too many people."),
                ("**Bad Word Filter**",   "Blocks configurable words/phrases using regex patterns."),
                ("**Config**",            "All rules are stored per-guild in the database and cached. Toggle via /setup or database editor."),
            ],
        ],
    },
    "setup": {
        "title":       "⚙️ Setup & Configuration",
        "description": "Configure Elura for your server.",
        "color":       0x3498DB,
        "pages": [
            [
                ("**/setup**",            "Run the interactive setup wizard (Administrator required).\nSelects log channel, muted role, and automod toggle."),
                ("**/config**",           "View the current saved configuration. (Administrator required)"),
                ("**Log Channel**",       "All moderation actions, automod events, and server events are sent here."),
                ("**Muted Role**",        "Role given to members when /mute is used. Create with no Send Messages permission."),
                ("**AutoMod Toggle**",    "Globally enable or disable all automod rules in one click."),
            ],
        ],
    },
    "permissions": {
        "title":       "🔐 Permission System",
        "description": "How Elura decides who can do what.",
        "color":       0xE74C3C,
        "pages": [
            [
                ("**Warn Role (Special)**",       f"Role ID `1415025708698308638` is required for /warn, /unwarn, /history."),
                ("**Ban Members**",               "Required for: /ban, /unban, /softban, /massban"),
                ("**Kick Members**",              "Required for: /kick, /masskick"),
                ("**Moderate Members**",          "Required for: /timeout, /untimeout"),
                ("**Manage Roles**",              "Required for: /mute, /unmute, /role_add, /role_remove"),
                ("**Manage Messages**",           "Required for: /clear"),
                ("**Manage Channels**",           "Required for: /slowmode, /lock, /unlock"),
                ("**Manage Nicknames**",          "Required for: /nick"),
                ("**Role Hierarchy**",            "You cannot punish members with equal or higher top roles. The server owner is always exempt from punishment."),
                ("**Bot Permissions**",           "Elura also checks its own permissions before acting, and reports clearly if it lacks them."),
            ],
        ],
    },
    "faq": {
        "title":       "❓ FAQ",
        "description": "Frequently asked questions about Elura.",
        "color":       0x2ECC71,
        "pages": [
            [
                ("Commands not showing?",    "Use /setup first. All commands are guild-specific and may take a few seconds to sync on first run."),
                ("Bot says it lacks permission?", "Go to Server Settings → Integrations → Elura and ensure it has the required permissions, or move its role higher."),
                ("Mute not working?",        "Ensure the muted role is configured via /setup and that the role has Send Messages: Denied on all channels."),
                ("Can I use prefix commands?", "No. Elura is slash-command only by design for cleaner UX."),
                ("How do timed punishments work?", "The bot checks every 30 seconds for expired mutes/timeouts and removes them automatically, even after restarts."),
                ("Can I add Elura to other servers?", "Elura is a single-guild bot by architecture. It's locked to one guild ID for performance and simplicity."),
            ],
        ],
    },
}

CATEGORY_OPTIONS = [
    discord.SelectOption(label="Moderation", value="moderation", emoji="🔨", description="Member punishment commands"),
    discord.SelectOption(label="AutoMod",    value="automod",    emoji="🤖", description="Automatic rule enforcement"),
    discord.SelectOption(label="Setup",      value="setup",      emoji="⚙️",  description="Configure the bot"),
    discord.SelectOption(label="Permissions",value="permissions",emoji="🔐", description="Who can do what"),
    discord.SelectOption(label="FAQ",        value="faq",        emoji="❓", description="Frequently asked questions"),
]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_page_embed(category: str, page: int) -> discord.Embed:
    data   = HELP_DATA[category]
    pages  = data["pages"]
    page   = max(0, min(page, len(pages) - 1))
    fields = pages[page]

    e = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=data["color"],
    )
    for name, value in fields:
        e.add_field(name=name, value=value, inline=False)

    total = len(pages)
    e.set_footer(text=f"Page {page + 1}/{total}  •  Use the dropdown to switch categories.")
    return e


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class HelpView(discord.ui.View):
    """
    Persistent help panel view.
    Holds current category and page state.
    """

    def __init__(self, invoker: discord.User | discord.Member) -> None:
        super().__init__(timeout=300)
        self.invoker  = invoker
        self.category = "moderation"
        self.page     = 0
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(CategorySelect(self.category))

        total_pages = len(HELP_DATA[self.category]["pages"])
        if total_pages > 1:
            self.add_item(PrevPageButton(self.page <= 0))
            self.add_item(NextPageButton(self.page >= total_pages - 1))

    def current_embed(self) -> discord.Embed:
        return build_page_embed(self.category, self.page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True  # Anyone can use the help panel


class CategorySelect(discord.ui.Select):
    def __init__(self, current: str) -> None:
        options = [
            discord.SelectOption(
                label=o.label,
                value=o.value,
                emoji=o.emoji,
                description=o.description,
                default=(o.value == current),
            )
            for o in CATEGORY_OPTIONS
        ]
        super().__init__(
            placeholder="Choose a category…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: HelpView = self.view  # type: ignore[assignment]
        view.category = self.values[0]
        view.page = 0
        view._rebuild()
        await interaction.response.edit_message(embed=view.current_embed(), view=view)


class PrevPageButton(discord.ui.Button):
    def __init__(self, disabled: bool) -> None:
        super().__init__(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: HelpView = self.view  # type: ignore[assignment]
        view.page = max(0, view.page - 1)
        view._rebuild()
        await interaction.response.edit_message(embed=view.current_embed(), view=view)


class NextPageButton(discord.ui.Button):
    def __init__(self, disabled: bool) -> None:
        super().__init__(label="Next ▶", style=discord.ButtonStyle.primary, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: HelpView = self.view  # type: ignore[assignment]
        total = len(HELP_DATA[view.category]["pages"])
        view.page = min(total - 1, view.page + 1)
        view._rebuild()
        await interaction.response.edit_message(embed=view.current_embed(), view=view)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class HelpCog(commands.Cog, name="Help"):
    """Interactive /help panel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Open the Elura interactive help panel.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def help(self, interaction: discord.Interaction) -> None:
        view = HelpView(invoker=interaction.user)
        await interaction.response.send_message(
            embed=view.current_embed(), view=view, ephemeral=True
        )
        # Track usage stat (fire-and-forget)
        try:
            await db.increment_help_stat("help", interaction.guild_id or GUILD_ID)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
