"""
cogs/help_cog.py — GL Bot Help System

Active cogs:
    moderation, automod, logging_cog, setup_cog,
    info, utility, about, warn_threshold,
    tickets, verification, qotd, suggestions,
    admin_dm, engagement

Removed: election, fun, extras, progression,
         mystery_event, tape, economy, search, welcome
"""

from __future__ import annotations

import discord
from discord.ext import commands

ACCENT = 0x3498DB

# ── Per-command detailed help ─────────────────────────────────────────────────
COMMAND_HELP: dict[str, dict] = {

    # ── Moderation ────────────────────────────────────────────────────────────
    "warn": {
        "usage": "gl.warn @user [reason]",
        "description": "Warn a member and log it to the database. Sends them a DM.",
        "examples": ["gl.warn @John spamming", "gl.warn @John"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "unwarn": {
        "usage": "gl.unwarn <case_id>",
        "description": "Remove an active warning by its case ID.",
        "examples": ["gl.unwarn 12"],
        "notes": "Get the case ID from `gl.history @user`. Requires **Moderator** (Tier 3)+.",
    },
    "history": {
        "usage": "gl.history @user [page]",
        "description": "View a member's full moderation history, paginated.",
        "examples": ["gl.history @John", "gl.history @John 2"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "mute": {
        "usage": "gl.mute @user [duration] [reason]",
        "description": "Mute a member using the muted role.",
        "examples": ["gl.mute @John 10m spamming", "gl.mute @John 1h"],
        "notes": "Units: `s` `m` `h` `d`. Tier 3 ≤1h, Tier 6+ ≤1 week.",
    },
    "unmute": {
        "usage": "gl.unmute @user [reason]",
        "description": "Remove a mute from a member.",
        "examples": ["gl.unmute @John"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "timeout": {
        "usage": "gl.timeout @user [duration] [reason]",
        "description": "Timeout a member using Discord's native timeout. Max 28 days.",
        "examples": ["gl.timeout @John 10m", "gl.timeout @John 1d breaking rules"],
        "notes": "Tier 3 ≤1h, Tier 6+ ≤1 week.",
    },
    "untimeout": {
        "usage": "gl.untimeout @user [reason]",
        "description": "Remove a timeout from a member.",
        "examples": ["gl.untimeout @John"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "kick": {
        "usage": "gl.kick @user [reason]",
        "description": "Kick a member from the server.",
        "examples": ["gl.kick @John breaking rules"],
        "notes": "Requires **Staff Manager** (Tier 6)+.",
    },
    "ban": {
        "usage": "gl.ban @user [delete_days] [reason]",
        "description": "Ban a member. `delete_days` deletes their recent messages (0–7).",
        "examples": ["gl.ban @John raiding", "gl.ban @John 7 spamming"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "unban": {
        "usage": "gl.unban <user_id> [reason]",
        "description": "Unban a user by their Discord ID.",
        "examples": ["gl.unban 123456789 appeal approved"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "softban": {
        "usage": "gl.softban @user [reason]",
        "description": "Ban then immediately unban to delete 7 days of messages.",
        "examples": ["gl.softban @John message spam"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "massban": {
        "usage": "gl.massban",
        "description": "Ban up to 1000 members at once. Confirms before proceeding.",
        "examples": ["gl.massban"],
        "notes": "⚠️ Owner only.",
    },
    "masskick": {
        "usage": "gl.masskick <id1,id2,id3> [reason]",
        "description": "Kick multiple members by IDs, comma-separated.",
        "examples": ["gl.masskick 111,222,333 raiding"],
        "notes": "Requires **Staff Manager** (Tier 6)+.",
    },
    "clear": {
        "usage": "gl.clear <amount> [@user]",
        "description": "Bulk delete messages. Optionally filter by user.",
        "examples": ["gl.clear 50", "gl.clear 20 @John"],
        "notes": "Max 100. Requires **Senior Moderator** (Tier 4)+.",
    },
    "slowmode": {
        "usage": "gl.slowmode <seconds> [#channel]",
        "description": "Set slowmode in a channel. Use `0` to disable.",
        "examples": ["gl.slowmode 5", "gl.slowmode 0"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "lock": {
        "usage": "gl.lock [#channel] [reason]",
        "description": "Lock a channel so members can't send messages.",
        "examples": ["gl.lock", "gl.lock #general raid happening"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "unlock": {
        "usage": "gl.unlock [#channel] [reason]",
        "description": "Unlock a previously locked channel.",
        "examples": ["gl.unlock #general"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "nick": {
        "usage": "gl.nick @user [nickname]",
        "description": "Change or reset a member's nickname.",
        "examples": ["gl.nick @John GL | John", "gl.nick @John"],
        "notes": "Requires **Community Manager** (Tier 8)+.",
    },
    "role_add": {
        "usage": "gl.role_add @user @role [reason]",
        "description": "Add a role to a member.",
        "examples": ["gl.role_add @John @Verified"],
        "notes": "Requires **Community Manager** (Tier 8)+.",
    },
    "role_remove": {
        "usage": "gl.role_remove @user @role [reason]",
        "description": "Remove a role from a member.",
        "examples": ["gl.role_remove @John @Verified"],
        "notes": "Requires **Community Manager** (Tier 8)+.",
    },
    "nuke": {
        "usage": "gl.nuke [#channel] [reason]",
        "description": "Delete and recreate a channel instantly.",
        "examples": ["gl.nuke", "gl.nuke #spam"],
        "notes": "⚠️ Requires **Head Moderator** (Tier 7)+. Irreversible.",
    },
    "note_add": {
        "usage": "gl.note_add @user <note>",
        "description": "Add a private staff note to a member.",
        "examples": ["gl.note_add @John previously warned for spam"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "note_list": {
        "usage": "gl.note_list @user",
        "description": "View all staff notes on a member.",
        "examples": ["gl.note_list @John"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "note_delete": {
        "usage": "gl.note_delete <note_id>",
        "description": "Delete a staff note by ID.",
        "examples": ["gl.note_delete 5"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },

    # ── Verification ──────────────────────────────────────────────────────────
    "postverify": {
        "usage": "gl.postverify",
        "description": "Post the verification button in this channel. Only needs to be run once.",
        "examples": ["gl.postverify"],
        "notes": "⚠️ Admin only. Run in your #verify channel.",
    },
    "forceverify": {
        "usage": "gl.forceverify @user",
        "description": "Manually grant the Verified role to a member.",
        "examples": ["gl.forceverify @John"],
        "notes": "Admin only.",
    },

    # ── Tickets ───────────────────────────────────────────────────────────────
    "ticket_setup": {
        "usage": "gl.ticket_setup #panel #transcripts [category] [@staff_role]",
        "description": "Set up the ticket system and post the panel button.",
        "examples": ["gl.ticket_setup #tickets #transcripts", "gl.ticket_setup #tickets #transcripts Tickets @Staff"],
        "notes": "Admin only. Run once.",
    },
    "ticket_config": {
        "usage": "gl.ticket_config",
        "description": "View current ticket system configuration.",
        "examples": ["gl.ticket_config"],
        "notes": "Staff only.",
    },
    "ticket_close": {
        "usage": "gl.ticket_close [#channel]",
        "description": "Force-close a ticket. Saves transcript and deletes the channel.",
        "examples": ["gl.ticket_close", "gl.ticket_close #ticket-0012"],
        "notes": "Staff only.",
    },
    "ticket_list": {
        "usage": "gl.ticket_list",
        "description": "List all currently open tickets.",
        "examples": ["gl.ticket_list"],
        "notes": "Staff only.",
    },

    # ── Suggestions ───────────────────────────────────────────────────────────
    "suggest": {
        "usage": "gl.suggest <your idea>",
        "description": "Submit a suggestion. Posts publicly for voting and sends to staff for review.",
        "examples": ["gl.suggest Add a weekly prediction channel"],
        "notes": "5 minute cooldown per user. Min 10 characters.",
    },
    "suggestion_config": {
        "usage": "gl.suggestion_config",
        "description": "View suggestion system configuration and pending count.",
        "examples": ["gl.suggestion_config"],
        "notes": "Admin only.",
    },

    # ── Info ──────────────────────────────────────────────────────────────────
    "userinfo": {
        "usage": "gl.userinfo [@user]",
        "description": "View detailed info about a member.",
        "examples": ["gl.userinfo", "gl.userinfo @John"],
        "notes": None,
    },
    "serverinfo": {
        "usage": "gl.serverinfo",
        "description": "View server stats — members, channels, roles, boosts.",
        "examples": ["gl.serverinfo"],
        "notes": None,
    },
    "botinfo": {
        "usage": "gl.botinfo",
        "description": "View bot information and stats.",
        "examples": ["gl.botinfo"],
        "notes": None,
    },

    # ── Utility ───────────────────────────────────────────────────────────────
    "ping": {
        "usage": "gl.ping",
        "description": "Check the bot's response latency.",
        "examples": ["gl.ping"],
        "notes": None,
    },
    "avatar": {
        "usage": "gl.avatar [@user] [server|global]",
        "description": "View a member's avatar.",
        "examples": ["gl.avatar", "gl.avatar @John global"],
        "notes": None,
    },
    "banner": {
        "usage": "gl.banner [@user]",
        "description": "View a member's profile banner.",
        "examples": ["gl.banner @John"],
        "notes": None,
    },
    "8ball": {
        "usage": "gl.8ball <question>",
        "description": "Ask the magic 8-ball a yes/no question.",
        "examples": ["gl.8ball Will GL win?"],
        "notes": None,
    },
    "poll": {
        "usage": "gl.poll <question> | <option1> | <option2>",
        "description": "Create a button-based poll with up to 4 options.",
        "examples": ["gl.poll Best striker? | Ronaldo | Messi | Mbappe"],
        "notes": "Separate question and options with `|`.",
    },
    "afk": {
        "usage": "gl.afk [reason]",
        "description": "Set your AFK status. Bot replies when someone pings you.",
        "examples": ["gl.afk", "gl.afk eating dinner"],
        "notes": "Clears automatically when you send a message.",
    },
    "remind": {
        "usage": "gl.remind <duration> <message>",
        "description": "Set a reminder. Bot DMs you when time is up.",
        "examples": ["gl.remind 1h Check the match results"],
        "notes": "Units: `s` `m` `h` `d`.",
    },
    "say": {
        "usage": "gl.say #channel <message>",
        "description": "Make the bot send a message in a channel.",
        "examples": ["gl.say #general Good morning GL!"],
        "notes": "Staff only.",
    },
    "embed": {
        "usage": "gl.embed #channel <title> | <description>",
        "description": "Send a custom embed in a channel.",
        "examples": ["gl.embed #announcements Match Day | Tonight at 8PM!"],
        "notes": "Staff only.",
    },

    # ── Engagement ────────────────────────────────────────────────────────────
    "engage": {
        "usage": "gl.engage",
        "description": "View engagement bot status — activity state, probability, channels.",
        "examples": ["gl.engage"],
        "notes": "Requires Manage Guild.",
    },
    "engage enable": {
        "usage": "gl.engage enable",
        "description": "Enable the engagement bot.",
        "examples": ["gl.engage enable"],
        "notes": None,
    },
    "engage disable": {
        "usage": "gl.engage disable",
        "description": "Disable the engagement bot.",
        "examples": ["gl.engage disable"],
        "notes": None,
    },
    "engage probability": {
        "usage": "gl.engage probability <1-100>",
        "description": "Set the base reaction probability as a percentage.",
        "examples": ["gl.engage probability 35"],
        "notes": "Adjusts based on server activity state.",
    },
    "engage cooldown": {
        "usage": "gl.engage cooldown <seconds>",
        "description": "Set the per-channel cooldown between reactions.",
        "examples": ["gl.engage cooldown 30"],
        "notes": None,
    },
    "engage channel": {
        "usage": "gl.engage channel <add|remove|list> [#channel]",
        "description": "Manage which channels the engagement bot reacts in.",
        "examples": ["gl.engage channel add #general", "gl.engage channel list"],
        "notes": "If no channels set, reacts in all channels.",
    },
    "engage profile": {
        "usage": "gl.engage profile [all|profile_1…profile_10]",
        "description": "View or set the active reaction profile.",
        "examples": ["gl.engage profile", "gl.engage profile profile_6"],
        "notes": "`all` picks a random profile per message.",
    },
    "engage prompts": {
        "usage": "gl.engage prompts <on|off|interval <seconds>>",
        "description": "Toggle conversation prompts when the server is inactive.",
        "examples": ["gl.engage prompts on", "gl.engage prompts interval 3600"],
        "notes": "Only fires when activity state is INACTIVE.",
    },
    "engage status": {
        "usage": "gl.engage status",
        "description": "Show current activity state and message count.",
        "examples": ["gl.engage status"],
        "notes": None,
    },

    # ── Setup ─────────────────────────────────────────────────────────────────
    "setup": {
        "usage": "gl.setup",
        "description": "Run the interactive server setup wizard.",
        "examples": ["gl.setup"],
        "notes": "Admin only.",
    },
    "config": {
        "usage": "gl.config",
        "description": "View current server configuration.",
        "examples": ["gl.config"],
        "notes": "Admin only.",
    },
    "perm_override": {
        "usage": "gl.perm_override @role <command> <true|false>",
        "description": "Set a command permission override for a role.",
        "examples": ["gl.perm_override @Mod warn true"],
        "notes": "Admin only.",
    },
}


# ── Category data ─────────────────────────────────────────────────────────────
CATEGORIES: dict[str, dict] = {
    "🛡️ Moderation": {
        "description": "Server moderation tools for staff.",
        "commands": [
            ("gl.warn @user [reason]",          "Warn a member."),
            ("gl.unwarn <case_id>",             "Remove a warning."),
            ("gl.history @user [page]",         "View mod history."),
            ("gl.note_add @user <note>",        "Add a staff note."),
            ("gl.note_list @user",              "List staff notes."),
            ("gl.note_delete <note_id>",        "Delete a staff note."),
            ("gl.mute @user [duration]",        "Mute a member."),
            ("gl.unmute @user",                 "Unmute a member."),
            ("gl.timeout @user [duration]",     "Timeout a member."),
            ("gl.untimeout @user",              "Remove a timeout."),
            ("gl.kick @user [reason]",          "Kick a member."),
            ("gl.ban @user [reason]",           "Ban a member."),
            ("gl.unban <id> [reason]",          "Unban a user."),
            ("gl.softban @user [reason]",       "Ban + unban to clear messages."),
            ("gl.clear <amount> [@user]",       "Delete messages."),
            ("gl.lock [#channel]",              "Lock a channel."),
            ("gl.unlock [#channel]",            "Unlock a channel."),
            ("gl.slowmode <seconds>",           "Set slowmode."),
            ("gl.nuke [#channel]",              "Nuke a channel."),
            ("gl.nick @user [nickname]",        "Change nickname."),
            ("gl.role_add @user @role",         "Add a role."),
            ("gl.role_remove @user @role",      "Remove a role."),
        ],
    },
    "✅ Verification": {
        "description": "Anti-alt account verification system.",
        "commands": [
            ("gl.postverify",       "Post the verify button. (Admin)"),
            ("gl.forceverify @user","Manually verify a member. (Admin)"),
        ],
    },
    "🎟️ Tickets": {
        "description": "Support ticket system.",
        "commands": [
            ("gl.ticket_setup #panel #log",  "Set up tickets. (Admin)"),
            ("gl.ticket_config",             "View ticket config."),
            ("gl.ticket_close [#channel]",   "Force-close a ticket."),
            ("gl.ticket_list",               "List open tickets."),
        ],
    },
    "💡 Suggestions": {
        "description": "Community suggestion system.",
        "commands": [
            ("gl.suggest <idea>",       "Submit a suggestion."),
            ("gl.suggestion_config",    "View suggestion config. (Admin)"),
        ],
    },
    "ℹ️ Info": {
        "description": "Server and member information.",
        "commands": [
            ("gl.userinfo [@user]", "Member info."),
            ("gl.serverinfo",       "Server stats."),
            ("gl.botinfo",          "Bot info."),
        ],
    },
    "🔧 Utility": {
        "description": "Everyday tools.",
        "commands": [
            ("gl.ping",                         "Check latency."),
            ("gl.avatar [@user]",               "View avatar."),
            ("gl.banner [@user]",               "View banner."),
            ("gl.8ball <question>",             "Ask the 8-ball."),
            ("gl.poll <q> | <o1> | <o2>",      "Create a poll."),
            ("gl.afk [reason]",                 "Set AFK status."),
            ("gl.remind <time> <msg>",          "Set a reminder."),
            ("gl.say #ch <msg>",                "Bot says something. (Staff)"),
            ("gl.embed #ch <title> | <desc>",   "Send an embed. (Staff)"),
        ],
    },
    "⚡ Engagement": {
        "description": "Reaction engagement bot controls.",
        "commands": [
            ("gl.engage",                           "View status."),
            ("gl.engage enable/disable",            "Toggle on/off."),
            ("gl.engage probability <1-100>",       "Set reaction chance."),
            ("gl.engage cooldown <seconds>",        "Set cooldown."),
            ("gl.engage channel add/remove #ch",    "Manage channels."),
            ("gl.engage profile [name]",            "Set reaction profile."),
            ("gl.engage prompts on/off",            "Toggle prompts."),
            ("gl.engage status",                    "Activity state."),
        ],
    },
    "⚙️ Setup": {
        "description": "Server setup and configuration.",
        "commands": [
            ("gl.setup",                                    "Run setup wizard. (Admin)"),
            ("gl.config",                                   "View server config. (Admin)"),
            ("gl.perm_override @role <cmd> <true|false>",  "Permission overrides. (Admin)"),
        ],
    },
}


# ── Views ─────────────────────────────────────────────────────────────────────
class CategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=cat, description=data["description"][:100])
            for cat, data in CATEGORIES.items()
        ]
        super().__init__(
            placeholder="📂 Choose a category…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        cat = self.values[0]
        embed = _category_embed(cat, CATEGORIES[cat])
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(CategorySelect())

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ── Embed builders ────────────────────────────────────────────────────────────
def _home_embed(prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="🏛️ Global League Bot — Help",
        description=(
            "Use the dropdown to browse categories.\n"
            f"**Prefix:** `{prefix}` · **Single command:** `{prefix}help <command>`\n"
            "**Support:** Open a ticket in the server."
        ),
        color=ACCENT,
    )
    for cat, data in CATEGORIES.items():
        embed.add_field(
            name=cat,
            value=f"{data['description']} `{len(data['commands'])} commands`",
            inline=True,
        )
    embed.set_footer(text="GL Bot • gl.help <command> for detailed help on any command")
    return embed


def _category_embed(cat: str, data: dict) -> discord.Embed:
    embed = discord.Embed(title=cat, description=data["description"], color=ACCENT)
    for name, desc in data["commands"]:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    embed.set_footer(text="GL Bot • gl.help <command> for detailed help")
    return embed


def _command_embed(name: str, data: dict) -> discord.Embed:
    embed = discord.Embed(title=f"📖 gl.{name}", color=ACCENT)
    embed.add_field(name="Usage",       value=f"`{data['usage']}`",     inline=False)
    embed.add_field(name="Description", value=data["description"],       inline=False)
    if data.get("examples"):
        embed.add_field(
            name="Examples",
            value="\n".join(f"`{e}`" for e in data["examples"]),
            inline=False,
        )
    if data.get("notes"):
        embed.add_field(name="📝 Notes", value=data["notes"], inline=False)
    embed.set_footer(text="GL Bot • [] = optional  <> = required")
    return embed


# ── Cog ───────────────────────────────────────────────────────────────────────
class HelpCog(commands.Cog, name="Help"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.remove_command("help")

    @commands.command(name="help", aliases=["h", "commands"])
    async def help_command(self, ctx: commands.Context, *, query: str = None) -> None:
        """Show help menu or detailed help for a specific command."""
        if query is None:
            await ctx.send(embed=_home_embed(ctx.prefix), view=HelpView())
            return

        query = query.lower().strip().lstrip("gl.").strip()

        # Direct match
        if query in COMMAND_HELP:
            await ctx.send(embed=_command_embed(query, COMMAND_HELP[query]))
            return

        # Fuzzy match
        matches = [k for k in COMMAND_HELP if query in k]
        if len(matches) == 1:
            await ctx.send(embed=_command_embed(matches[0], COMMAND_HELP[matches[0]]))
            return
        if len(matches) > 1:
            embed = discord.Embed(
                title=f"🔍 Multiple matches for `{query}`",
                description="\n".join(f"`gl.{m}`" for m in matches[:10]),
                color=ACCENT,
            )
            embed.set_footer(text="Be more specific — e.g. gl.help qotd add")
            await ctx.send(embed=embed)
            return

        # Category match
        cat_match = next((c for c in CATEGORIES if query in c.lower()), None)
        if cat_match:
            await ctx.send(embed=_category_embed(cat_match, CATEGORIES[cat_match]))
            return

        await ctx.send(
            f"❓ No command or category found for `{query}`.\n"
            f"Use `gl.help` to browse all categories."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
