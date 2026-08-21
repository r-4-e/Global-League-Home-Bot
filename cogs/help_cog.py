"""
cogs/help_cog.py — GL Bot Help System

Category dropdown with paginated embeds.
Covers every command in every cog.
Usage: gl.help
"""

from __future__ import annotations

import discord
from discord.ext import commands

ACCENT = 0x3498DB  # info blue — matches config.COLOR_INFO

# ── Command data ──────────────────────────────────────────────────────────────
CATEGORIES: dict[str, dict] = {

    "🛡️ Moderation": {
        "description": "Server moderation tools for staff.",
        "commands": [
            ("gl.warn @user [reason]",       "Warn a member and log it."),
            ("gl.unwarn <case_id>",          "Remove a warning by case ID."),
            ("gl.history @user [page]",      "View a member's moderation history."),
            ("gl.note_add @user <note>",     "Add a private staff note to a member."),
            ("gl.note_list @user",           "List all staff notes for a member."),
            ("gl.note_delete <note_id>",     "Delete a staff note by ID."),
            ("gl.mute @user [duration] [reason]", "Mute a member (e.g. 10m, 1h, 7d)."),
            ("gl.unmute @user [reason]",     "Remove a member's mute."),
            ("gl.timeout @user [duration] [reason]", "Timeout a member."),
            ("gl.untimeout @user [reason]",  "Remove a member's timeout."),
            ("gl.kick @user [reason]",       "Kick a member from the server."),
            ("gl.ban @user [reason]",        "Ban a member from the server."),
        ],
    },

    "⚙️ AutoMod": {
        "description": "Automatic moderation rule configuration.",
        "commands": [
            ("Automatic", "AutoMod runs silently in the background."),
            ("Rules",     "Anti-spam, anti-duplicate, anti-caps, anti-link, anti-invite, anti-mention, bad words."),
            ("gl.setup",  "Run the setup wizard to configure AutoMod rules and channels."),
            ("gl.config", "View current server configuration."),
            ("gl.perm_override <@role> <command> <true/false>", "Override command permissions for a role."),
        ],
    },

    "✅ Verification": {
        "description": "Anti-alt account verification system.",
        "commands": [
            ("gl.postverify",           "Post the verification button in this channel. (Admin only)"),
            ("gl.forceverify @user",    "Manually grant the Verified role to a member. (Admin only)"),
        ],
    },

    "💰 Economy": {
        "description": "Server economy — earn, spend, and trade GL Coins.",
        "commands": [
            ("gl.balance [@user]",       "Check your wallet and bank balance."),
            ("gl.money [@user]",         "Alias for balance."),
            ("gl.deposit <amount/all>",  "Deposit coins into your bank."),
            ("gl.withdraw <amount/all>", "Withdraw coins from your bank."),
            ("gl.give @user <amount>",   "Give coins to another member."),
            ("gl.leaderboard",           "View the richest members in the server."),
        ],
    },

    "🗳️ Elections": {
        "description": "GL Democratic Election system.",
        "commands": [
            ("gl.election_create <title> | <candidate1> | <candidate2> ...", "Create a new election. (Admin)"),
            ("gl.election_vote",    "Open the voting panel for the active election."),
            ("gl.election_results", "View current election standings."),
            ("gl.election_end",     "End the election and announce results. (Admin)"),
            ("gl.election_cancel",  "Cancel the active election. (Admin)"),
        ],
    },

    "❓ QOTD": {
        "description": "Question of the Day — daily auto-posted questions.",
        "commands": [
            ("gl.qotd",                     "View QOTD settings and status."),
            ("gl.qotd add <question>",       "Add a question to the bank. (Staff)"),
            ("gl.qotd remove <id>",          "Remove a question by ID. (Staff)"),
            ("gl.qotd list",                 "List all pending questions. (Staff)"),
            ("gl.qotd preview",              "Preview the next question. (Staff)"),
            ("gl.qotd post",                 "Force-post a QOTD right now. (Staff)"),
            ("gl.qotd setchannel #channel",  "Set the QOTD channel. (Staff)"),
            ("gl.qotd setrole @role",        "Set the ping role. (Staff)"),
            ("gl.qotd settime HH:MM",        "Set daily post time in UTC. (Staff)"),
        ],
    },

    "🎟️ Tickets": {
        "description": "Support ticket system.",
        "commands": [
            ("gl.ticket_setup #panel_channel #log_channel @support_role", "Set up the ticket system. (Admin)"),
            ("gl.ticket_config", "View current ticket configuration."),
            ("🎟 Open a Ticket button", "Members click the panel button to open a ticket."),
        ],
    },

    "🎉 Fun": {
        "description": "Entertainment and games.",
        "commands": [
            ("/meme",              "Fetch a random meme from Reddit."),
            ("/fact",              "Get a random interesting fact."),
            ("/joke",              "Get a random joke."),
            ("/botinfo",           "View bot stats and information."),
            ("/would_you_rather",  "Would you rather...?"),
            ("/truth_or_dare",     "Get a random truth or dare."),
            ("/ship @user1 @user2","Calculate compatibility between two members."),
            ("/rate <thing>",      "Rate anything out of 10."),
            ("/reverse <text>",    "Reverse your text."),
        ],
    },

    "🔍 Extras": {
        "description": "Extra tools and mini-games.",
        "commands": [
            ("gl.lookup @user",          "Full member lookup with all details."),
            ("gl.warn_history @user [page]", "View a member's full warning history."),
            ("gl.dice [NdN]",            "Roll dice. e.g. gl.dice 2d6"),
            ("gl.lyrics <song>",         "Search for song lyrics."),
            ("gl.counting_setup [#channel]", "Set up a counting channel."),
        ],
    },

    "ℹ️ Info": {
        "description": "Server and member information.",
        "commands": [
            ("gl.userinfo [@user]",      "View detailed info about a member."),
            ("gl.serverinfo",            "View server statistics and info."),
            ("gl.botinfo",               "View bot information."),
            ("gl.antiraid_setup <enabled> [threshold] [window] [action]", "Configure anti-raid protection. (Admin)"),
            ("gl.antiraid_status",       "Check anti-raid configuration."),
            ("gl.antiraid_unlock",       "Unlock the server after a raid. (Admin)"),
        ],
    },

    "🔧 Utility": {
        "description": "Handy everyday tools.",
        "commands": [
            ("gl.ping",                          "Check bot latency."),
            ("gl.avatar [@user] [server/global]","View a member's avatar."),
            ("gl.banner [@user]",                "View a member's banner."),
            ("gl.8ball <question>",              "Ask the magic 8-ball."),
            ("gl.poll <question> | <opt1> | <opt2>", "Create a button poll."),
            ("gl.afk [reason]",                  "Set your AFK status."),
            ("gl.remind <duration> <message>",   "Set a reminder. e.g. gl.remind 1h Study"),
            ("gl.say #channel <message>",        "Make the bot say something in a channel. (Staff)"),
            ("gl.embed #channel <title> | <desc>","Send a custom embed. (Staff)"),
        ],
    },

    "🔎 Search": {
        "description": "Web search from Discord.",
        "commands": [
            ("gl.search <query>", "Search the web and return top results."),
        ],
    },

    "🌟 Welcome": {
        "description": "Welcome and leave message configuration.",
        "commands": [
            ("gl.welcome_setup #welcome_ch #leave_ch @member_role", "Configure welcome/leave messages. (Admin)"),
            ("gl.welcome_setext <text>",  "Set a custom welcome message. Use {mention} for the member."),
            ("gl.welcome_test",           "Preview the welcome message."),
            ("gl.welcome_config",         "View current welcome configuration."),
            ("gl.welcome_disable <welcome/leave/both>", "Disable welcome or leave messages."),
        ],
    },

    "🎭 Mystery Event": {
        "description": "GL Mystery Word Event — guess the hidden word.",
        "commands": [
            ("gl.mystery_set <word>",       "Set the mystery word. (Dev)"),
            ("gl.mystery_clue <clue>",      "Add a clue for the mystery word. (Dev)"),
            ("gl.mystery_spin",             "Spin for a prize winner. (Dev)"),
            ("gl.mystery_reset",            "Reset the mystery event. (Dev)"),
            ("gl.mystery_status",           "Check the current event status. (Dev)"),
            ("gl.mystery_clues",            "View all published clues."),
            ("gl.mystery_qualifiers",       "See who has qualified so far."),
        ],
    },

    "📜 About": {
        "description": "About this bot.",
        "commands": [
            ("gl.about", "View information about the GL Bot."),
        ],
    },

    "⚙️ Setup": {
        "description": "Server setup and configuration.",
        "commands": [
            ("gl.setup",                                     "Run the interactive server setup wizard. (Admin)"),
            ("gl.config",                                    "View current server config. (Admin)"),
            ("gl.perm_override @role <command> <true/false>","Set command permission overrides. (Admin)"),
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
            "Use the dropdown below to browse command categories.\n\n"
            f"**Prefix:** `{prefix}` · **Slash commands:** `/`\n"
            "**Support:** Open a ticket in the server."
        ),
        color=ACCENT,
    )
    for cat, data in CATEGORIES.items():
        cmd_count = len(data["commands"])
        embed.add_field(
            name=cat,
            value=f"{data['description']} `{cmd_count} commands`",
            inline=True,
        )
    embed.set_footer(text="GL Bot • Select a category to see commands")
    return embed


def _category_embed(cat: str, data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=cat,
        description=data["description"],
        color=ACCENT,
    )
    for name, desc in data["commands"]:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    embed.set_footer(text="GL Bot • Use the dropdown to switch categories")
    return embed


# ── Cog ───────────────────────────────────────────────────────────────────────
class HelpCog(commands.Cog, name="Help"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Remove default help command so gl.help works
        self.bot.remove_command("help")

    @commands.command(name="help", aliases=["h", "commands"])
    async def help_command(self, ctx: commands.Context, *, category: str = None) -> None:
        """Show the help menu. Optionally pass a category name."""
        if category:
            # Try to find a matching category
            match = next(
                (cat for cat in CATEGORIES if category.lower() in cat.lower()),
                None,
            )
            if match:
                embed = _category_embed(match, CATEGORIES[match])
                await ctx.send(embed=embed)
                return
            await ctx.send(f"❌ Category `{category}` not found. Use `gl.help` to browse all categories.")
            return

        embed = _home_embed(ctx.prefix)
        view = HelpView()
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
