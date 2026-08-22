"""
cogs/help_cog.py — GL Bot Help System

gl.help              — full category dropdown
gl.help <command>    — detailed help for one command
"""

from __future__ import annotations

import discord
from discord.ext import commands

ACCENT = 0x3498DB

# ── Per-command detailed help ─────────────────────────────────────────────────
# Each entry: "command_name": (usage, description, examples, notes)
COMMAND_HELP: dict[str, dict] = {

    # ── Moderation ────────────────────────────────────────────────────────────
    "warn": {
        "usage": "gl.warn @user [reason]",
        "description": "Warn a member and log it to the database. Sends them a DM.",
        "examples": ["gl.warn @John spamming", "gl.warn @John"],
        "notes": "Requires **Moderator** (Tier 3) or higher.",
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
        "description": "Mute a member using the muted role. Duration is optional.",
        "examples": ["gl.mute @John 10m spamming", "gl.mute @John 1h", "gl.mute @John"],
        "notes": "Duration units: `s`, `m`, `h`, `d`. Requires **Moderator** (Tier 3)+. Tier 3 limited to 1h, Tier 6+ up to 1 week.",
    },
    "unmute": {
        "usage": "gl.unmute @user [reason]",
        "description": "Remove a mute from a member.",
        "examples": ["gl.unmute @John", "gl.unmute @John appeal approved"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "timeout": {
        "usage": "gl.timeout @user [duration] [reason]",
        "description": "Timeout a member using Discord's native timeout. Max 28 days.",
        "examples": ["gl.timeout @John 10m", "gl.timeout @John 1d breaking rules"],
        "notes": "Duration units: `s`, `m`, `h`, `d`. Tier 3 limited to 1h, Tier 6+ up to 1 week.",
    },
    "untimeout": {
        "usage": "gl.untimeout @user [reason]",
        "description": "Remove a timeout from a member.",
        "examples": ["gl.untimeout @John", "gl.untimeout @John appeal approved"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },
    "kick": {
        "usage": "gl.kick @user [reason]",
        "description": "Kick a member from the server. They can rejoin with an invite.",
        "examples": ["gl.kick @John breaking rules"],
        "notes": "Requires **Staff Manager** (Tier 6)+.",
    },
    "ban": {
        "usage": "gl.ban @user [delete_days] [reason]",
        "description": "Ban a member. `delete_days` deletes their recent messages (0–7 days).",
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
        "description": "Ban then immediately unban to delete 7 days of messages without permanently banning.",
        "examples": ["gl.softban @John message spam"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "massban": {
        "usage": "gl.massban",
        "description": "Ban up to 1000 members at once. Asks for confirmation before proceeding.",
        "examples": ["gl.massban"],
        "notes": "⚠️ **Owner only.** Irreversible — use with extreme caution.",
    },
    "masskick": {
        "usage": "gl.masskick <id1,id2,id3> [reason]",
        "description": "Kick multiple members by their user IDs, comma-separated.",
        "examples": ["gl.masskick 111,222,333 raiding"],
        "notes": "Requires **Staff Manager** (Tier 6)+.",
    },
    "clear": {
        "usage": "gl.clear <amount> [@user]",
        "description": "Bulk delete messages. Optionally filter by a specific user.",
        "examples": ["gl.clear 50", "gl.clear 20 @John"],
        "notes": "Max 100 messages. Requires **Senior Moderator** (Tier 4)+.",
    },
    "slowmode": {
        "usage": "gl.slowmode <seconds> [#channel]",
        "description": "Set slowmode in a channel. Use `0` to disable.",
        "examples": ["gl.slowmode 5", "gl.slowmode 10 #general", "gl.slowmode 0"],
        "notes": "Max 21600 seconds (6h). Requires **Head Moderator** (Tier 7)+.",
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
        "examples": ["gl.unlock", "gl.unlock #general raid over"],
        "notes": "Requires **Head Moderator** (Tier 7)+.",
    },
    "nick": {
        "usage": "gl.nick @user [nickname]",
        "description": "Change a member's nickname. Leave blank to reset it.",
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
        "description": "Delete and recreate a channel instantly, clearing all messages.",
        "examples": ["gl.nuke", "gl.nuke #spam"],
        "notes": "⚠️ Requires **Head Moderator** (Tier 7)+. Irreversible.",
    },
    "note_add": {
        "usage": "gl.note_add @user <note>",
        "description": "Add a private staff note to a member. Only visible to staff.",
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
        "description": "Delete a staff note by its ID.",
        "examples": ["gl.note_delete 5"],
        "notes": "Requires **Moderator** (Tier 3)+.",
    },

    # ── Verification ──────────────────────────────────────────────────────────
    "postverify": {
        "usage": "gl.postverify",
        "description": "Post the verification button embed in the current channel. Only needs to be done once — the button survives bot restarts.",
        "examples": ["gl.postverify"],
        "notes": "⚠️ Admin only. Run this in your #verify channel.",
    },
    "forceverify": {
        "usage": "gl.forceverify @user",
        "description": "Manually grant the Verified role to a member who got falsely flagged.",
        "examples": ["gl.forceverify @John"],
        "notes": "Admin only.",
    },

    # ── QOTD ─────────────────────────────────────────────────────────────────
    "qotd": {
        "usage": "gl.qotd",
        "description": "View QOTD settings — channel, post time, ping role, question bank size.",
        "examples": ["gl.qotd"],
        "notes": "Requires Manage Guild.",
    },
    "qotd add": {
        "usage": "gl.qotd add <question>",
        "description": "Add a question to the daily question bank.",
        "examples": ["gl.qotd add Who is the best player in GL right now?"],
        "notes": "Questions are posted in order. Max 500 characters.",
    },
    "qotd remove": {
        "usage": "gl.qotd remove <id>",
        "description": "Remove a question from the bank by its ID.",
        "examples": ["gl.qotd remove 12"],
        "notes": "Get the ID from `gl.qotd list`.",
    },
    "qotd list": {
        "usage": "gl.qotd list",
        "description": "List all pending (unused) questions in the bank.",
        "examples": ["gl.qotd list"],
        "notes": "Shows 10 per page.",
    },
    "qotd post": {
        "usage": "gl.qotd post",
        "description": "Force-post a QOTD right now without waiting for the daily timer.",
        "examples": ["gl.qotd post"],
        "notes": "Also resets the daily timer so it won't double-post today.",
    },
    "qotd setchannel": {
        "usage": "gl.qotd setchannel #channel",
        "description": "Set which channel QOTD posts in daily.",
        "examples": ["gl.qotd setchannel #qotd"],
        "notes": "Bot needs Send Messages and Create Public Threads in that channel.",
    },
    "qotd setrole": {
        "usage": "gl.qotd setrole @role",
        "description": "Set a role to ping when QOTD posts.",
        "examples": ["gl.qotd setrole @QOTD"],
        "notes": "Members can self-assign this role to opt in.",
    },
    "qotd settime": {
        "usage": "gl.qotd settime HH:MM",
        "description": "Set the daily post time in UTC 24-hour format.",
        "examples": ["gl.qotd settime 09:00", "gl.qotd settime 18:30"],
        "notes": "Time is always UTC.",
    },
    "qotd debug": {
        "usage": "gl.qotd debug",
        "description": "Show raw database values for QOTD config — useful for diagnosing issues.",
        "examples": ["gl.qotd debug"],
        "notes": "Staff only.",
    },

    # ── Tickets ───────────────────────────────────────────────────────────────
    "ticket_setup": {
        "usage": "gl.ticket_setup #panel #transcripts [category] [@staff_role]",
        "description": "Set up the ticket system. Posts the ticket panel button in the panel channel.",
        "examples": [
            "gl.ticket_setup #tickets #transcripts",
            "gl.ticket_setup #tickets #transcripts Tickets @Staff",
        ],
        "notes": "Admin only. Run once. The button survives bot restarts.",
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
        "notes": "Staff only. If no channel is specified, closes the current channel.",
    },
    "ticket_list": {
        "usage": "gl.ticket_list",
        "description": "List all currently open tickets and who opened them.",
        "examples": ["gl.ticket_list"],
        "notes": "Staff only.",
    },

    # ── Economy ───────────────────────────────────────────────────────────────
    "balance": {
        "usage": "gl.balance [@user]",
        "description": "Check your wallet and bank balance. Mention someone to check theirs.",
        "examples": ["gl.balance", "gl.balance @John"],
        "notes": "Alias: `gl.money`",
    },
    "deposit": {
        "usage": "gl.deposit <amount|all>",
        "description": "Deposit coins from your wallet into your bank.",
        "examples": ["gl.deposit 500", "gl.deposit all"],
        "notes": None,
    },
    "withdraw": {
        "usage": "gl.withdraw <amount|all>",
        "description": "Withdraw coins from your bank into your wallet.",
        "examples": ["gl.withdraw 200", "gl.withdraw all"],
        "notes": None,
    },
    "give": {
        "usage": "gl.give @user <amount>",
        "description": "Give coins from your wallet to another member.",
        "examples": ["gl.give @John 100"],
        "notes": None,
    },
    "leaderboard": {
        "usage": "gl.leaderboard",
        "description": "View the richest members in the server.",
        "examples": ["gl.leaderboard"],
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
        "description": "View a member's avatar. Defaults to server avatar if they have one.",
        "examples": ["gl.avatar", "gl.avatar @John", "gl.avatar @John global"],
        "notes": None,
    },
    "banner": {
        "usage": "gl.banner [@user]",
        "description": "View a member's profile banner.",
        "examples": ["gl.banner", "gl.banner @John"],
        "notes": None,
    },
    "8ball": {
        "usage": "gl.8ball <question>",
        "description": "Ask the magic 8-ball a yes/no question.",
        "examples": ["gl.8ball Will GL win the next match?"],
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
        "description": "Set your AFK status. Bot will reply when someone pings you.",
        "examples": ["gl.afk", "gl.afk eating dinner"],
        "notes": "AFK clears automatically when you send a message.",
    },
    "remind": {
        "usage": "gl.remind <duration> <message>",
        "description": "Set a reminder. Bot DMs you when the time is up.",
        "examples": ["gl.remind 1h Check the match results", "gl.remind 30m Meeting"],
        "notes": "Duration units: `s`, `m`, `h`, `d`.",
    },
    "say": {
        "usage": "gl.say #channel <message>",
        "description": "Make the bot send a message in a specific channel.",
        "examples": ["gl.say #general Good morning GL!"],
        "notes": "Staff only.",
    },
    "embed": {
        "usage": "gl.embed #channel <title> | <description>",
        "description": "Send a custom embed in a channel.",
        "examples": ["gl.embed #announcements Match Day | Today's match starts at 8PM!"],
        "notes": "Staff only. Separate title and description with `|`.",
    },

    # ── Info ──────────────────────────────────────────────────────────────────
    "userinfo": {
        "usage": "gl.userinfo [@user]",
        "description": "View detailed info about a member — join date, roles, cases, status.",
        "examples": ["gl.userinfo", "gl.userinfo @John"],
        "notes": None,
    },
    "serverinfo": {
        "usage": "gl.serverinfo",
        "description": "View server stats — member count, channels, roles, boost level.",
        "examples": ["gl.serverinfo"],
        "notes": None,
    },

    # ── Welcome ───────────────────────────────────────────────────────────────
    "welcome_setup": {
        "usage": "gl.welcome_setup #welcome_ch #leave_ch @member_role",
        "description": "Configure welcome and leave messages.",
        "examples": ["gl.welcome_setup #welcome #leave @Member"],
        "notes": "Admin only.",
    },
    "welcome_test": {
        "usage": "gl.welcome_test",
        "description": "Preview the welcome message as if you just joined.",
        "examples": ["gl.welcome_test"],
        "notes": "Admin only.",
    },

    # ── Engage ────────────────────────────────────────────────────────────────
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
        "notes": "Actual probability adjusts based on server activity state.",
    },
    "engage cooldown": {
        "usage": "gl.engage cooldown <seconds>",
        "description": "Set the per-channel cooldown between reactions.",
        "examples": ["gl.engage cooldown 30"],
        "notes": None,
    },
    "engage channel": {
        "usage": "gl.engage channel <add|remove|list> [#channel]",
        "description": "Add or remove channels from the engagement bot's allowed list.",
        "examples": ["gl.engage channel add #general", "gl.engage channel remove #staff", "gl.engage channel list"],
        "notes": "If no channels are set, bot reacts in all channels.",
    },
    "engage profile": {
        "usage": "gl.engage profile [all|profile_1...profile_10]",
        "description": "View or set the active reaction profile.",
        "examples": ["gl.engage profile", "gl.engage profile profile_1", "gl.engage profile all"],
        "notes": "`all` randomly picks a profile per message.",
    },
    "engage prompts": {
        "usage": "gl.engage prompts <on|off|interval <seconds>>",
        "description": "Enable/disable conversation prompts when server is inactive.",
        "examples": ["gl.engage prompts on", "gl.engage prompts interval 3600"],
        "notes": "Prompts only fire when activity state is INACTIVE.",
    },
    "engage status": {
        "usage": "gl.engage status",
        "description": "Show current activity state and recent message count.",
        "examples": ["gl.engage status"],
        "notes": None,
    },

    # ── Mystery Event ─────────────────────────────────────────────────────────
    "mystery_set": {
        "usage": "gl.mystery_set <word>",
        "description": "Set the secret mystery word for the event.",
        "examples": ["gl.mystery_set champion"],
        "notes": "Dev/Owner only.",
    },
    "mystery_clue": {
        "usage": "gl.mystery_clue <clue>",
        "description": "Post a new clue for the mystery word.",
        "examples": ["gl.mystery_clue It starts with the letter C"],
        "notes": "Dev/Owner only.",
    },
    "mystery_clues": {
        "usage": "gl.mystery_clues",
        "description": "View all published clues for the current mystery event.",
        "examples": ["gl.mystery_clues"],
        "notes": None,
    },
    "mystery_qualifiers": {
        "usage": "gl.mystery_qualifiers",
        "description": "See which members have correctly guessed and qualified.",
        "examples": ["gl.mystery_qualifiers"],
        "notes": None,
    },
}


# ── Category data ─────────────────────────────────────────────────────────────
CATEGORIES: dict[str, dict] = {
    "🛡️ Moderation": {
        "description": "Server moderation tools for staff.",
        "commands": [
            ("gl.warn @user [reason]", "Warn a member."),
            ("gl.unwarn <case_id>", "Remove a warning."),
            ("gl.history @user [page]", "View mod history."),
            ("gl.note_add @user <note>", "Add a staff note."),
            ("gl.note_list @user", "List staff notes."),
            ("gl.note_delete <note_id>", "Delete a staff note."),
            ("gl.mute @user [duration] [reason]", "Mute a member."),
            ("gl.unmute @user [reason]", "Unmute a member."),
            ("gl.timeout @user [duration] [reason]", "Timeout a member."),
            ("gl.untimeout @user [reason]", "Remove a timeout."),
            ("gl.kick @user [reason]", "Kick a member."),
            ("gl.ban @user [reason]", "Ban a member."),
            ("gl.unban <id> [reason]", "Unban a user."),
            ("gl.softban @user [reason]", "Ban + unban to clear messages."),
            ("gl.clear <amount> [@user]", "Delete messages."),
            ("gl.lock [#channel]", "Lock a channel."),
            ("gl.unlock [#channel]", "Unlock a channel."),
            ("gl.slowmode <seconds>", "Set slowmode."),
            ("gl.nuke [#channel]", "Nuke a channel."),
            ("gl.nick @user [nickname]", "Change nickname."),
        ],
    },
    "✅ Verification": {
        "description": "Anti-alt account verification system.",
        "commands": [
            ("gl.postverify", "Post the verify button. (Admin)"),
            ("gl.forceverify @user", "Manually verify a member. (Admin)"),
        ],
    },
    "❓ QOTD": {
        "description": "Question of the Day — daily auto-posted questions.",
        "commands": [
            ("gl.qotd", "View QOTD settings."),
            ("gl.qotd add <question>", "Add a question."),
            ("gl.qotd remove <id>", "Remove a question."),
            ("gl.qotd list", "List all questions."),
            ("gl.qotd preview", "Preview next question."),
            ("gl.qotd post", "Force-post now."),
            ("gl.qotd setchannel #ch", "Set the channel."),
            ("gl.qotd setrole @role", "Set the ping role."),
            ("gl.qotd settime HH:MM", "Set post time (UTC)."),
            ("gl.qotd debug", "Debug DB values."),
        ],
    },
    "🎟️ Tickets": {
        "description": "Support ticket system.",
        "commands": [
            ("gl.ticket_setup #panel #log [@role]", "Set up tickets. (Admin)"),
            ("gl.ticket_config", "View ticket config."),
            ("gl.ticket_close [#channel]", "Force-close a ticket."),
            ("gl.ticket_list", "List open tickets."),
        ],
    },
    "💰 Economy": {
        "description": "GL server economy.",
        "commands": [
            ("gl.balance [@user]", "Check balance."),
            ("gl.deposit <amount|all>", "Deposit to bank."),
            ("gl.withdraw <amount|all>", "Withdraw from bank."),
            ("gl.give @user <amount>", "Give coins to a member."),
            ("gl.leaderboard", "Richest members."),
        ],
    },
    "🎉 Fun": {
        "description": "Entertainment commands.",
        "commands": [
            ("/meme", "Random meme."),
            ("/fact", "Random fact."),
            ("/joke", "Random joke."),
            ("/would_you_rather", "Would you rather?"),
            ("/truth_or_dare", "Truth or dare."),
            ("/ship @u1 @u2", "Ship two members."),
            ("/rate <thing>", "Rate anything."),
            ("/reverse <text>", "Reverse text."),
        ],
    },
    "🔧 Utility": {
        "description": "Everyday tools.",
        "commands": [
            ("gl.ping", "Check latency."),
            ("gl.avatar [@user]", "View avatar."),
            ("gl.banner [@user]", "View banner."),
            ("gl.8ball <question>", "Ask the 8-ball."),
            ("gl.poll <q> | <o1> | <o2>", "Create a poll."),
            ("gl.afk [reason]", "Set AFK status."),
            ("gl.remind <time> <msg>", "Set a reminder."),
            ("gl.say #ch <msg>", "Bot says something."),
            ("gl.embed #ch <title> | <desc>", "Send an embed."),
        ],
    },
    "ℹ️ Info": {
        "description": "Server and member information.",
        "commands": [
            ("gl.userinfo [@user]", "Member info."),
            ("gl.serverinfo", "Server stats."),
            ("gl.botinfo", "Bot info."),
        ],
    },
    "⚡ Engagement": {
        "description": "Reaction engagement bot controls.",
        "commands": [
            ("gl.engage", "View status."),
            ("gl.engage enable/disable", "Toggle on/off."),
            ("gl.engage probability <1-100>", "Set reaction chance."),
            ("gl.engage cooldown <seconds>", "Set cooldown."),
            ("gl.engage channel add/remove #ch", "Manage channels."),
            ("gl.engage profile [name]", "Set reaction profile."),
            ("gl.engage prompts on/off", "Toggle prompts."),
            ("gl.engage status", "Activity state."),
        ],
    },
    "🌟 Welcome": {
        "description": "Welcome and leave messages.",
        "commands": [
            ("gl.welcome_setup #ch #ch @role", "Configure welcome."),
            ("gl.welcome_test", "Preview welcome message."),
            ("gl.welcome_config", "View config."),
            ("gl.welcome_disable <welcome|leave|both>", "Disable messages."),
        ],
    },
    "🎭 Mystery Event": {
        "description": "GL Mystery Word Event.",
        "commands": [
            ("gl.mystery_set <word>", "Set mystery word."),
            ("gl.mystery_clue <clue>", "Add a clue."),
            ("gl.mystery_clues", "View clues."),
            ("gl.mystery_qualifiers", "View qualifiers."),
            ("gl.mystery_spin", "Pick a winner."),
            ("gl.mystery_reset", "Reset event."),
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
        data = CATEGORIES[cat]
        embed = _category_embed(cat, data)
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
    embed.set_footer(text="GL Bot • gl.help <command> for detailed help on any command")
    return embed


def _command_embed(name: str, data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"📖 gl.{name}",
        color=ACCENT,
    )
    embed.add_field(name="Usage", value=f"`{data['usage']}`", inline=False)
    embed.add_field(name="Description", value=data["description"], inline=False)
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
            embed = _home_embed(ctx.prefix)
            view = HelpView()
            await ctx.send(embed=embed, view=view)
            return

        query = query.lower().strip()

        # Remove "gl." prefix if someone types gl.help gl.warn
        if query.startswith("gl."):
            query = query[3:]

        # Direct command match
        if query in COMMAND_HELP:
            await ctx.send(embed=_command_embed(query, COMMAND_HELP[query]))
            return

        # Fuzzy match — find commands that start with or contain the query
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
        cat_match = next(
            (cat for cat in CATEGORIES if query in cat.lower()),
            None,
        )
        if cat_match:
            await ctx.send(embed=_category_embed(cat_match, CATEGORIES[cat_match]))
            return

        await ctx.send(
            f"❓ No command or category found for `{query}`.\n"
            f"Use `gl.help` to browse all categories."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
