"""
cogs/help_cog.py — Help command for Global League Bot.
Usage: gl.help | gl.help <command>
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

COMMANDS = {
    # Moderation
    "warn":        ("Moderation", "gl.warn @user [reason]",               "Warn a member. Requires Warn Role."),
    "unwarn":      ("Moderation", "gl.unwarn <case_id>",                  "Remove a warning by case ID."),
    "history":     ("Moderation", "gl.history @user [page]",              "View mod history for a user."),
    "note_add":    ("Moderation", "gl.note_add @user <content>",          "Add a staff note."),
    "note_list":   ("Moderation", "gl.note_list @user",                   "View staff notes for a user."),
    "note_delete": ("Moderation", "gl.note_delete <note_id>",             "Delete a staff note."),
    "mute":        ("Moderation", "gl.mute @user [duration] [reason]",    "Mute a member. e.g. 10m 2h 1d"),
    "unmute":      ("Moderation", "gl.unmute @user [reason]",             "Remove mute from a member."),
    "timeout":     ("Moderation", "gl.timeout @user [duration] [reason]", "Discord timeout. Max 28d."),
    "untimeout":   ("Moderation", "gl.untimeout @user [reason]",          "Remove a timeout."),
    "kick":        ("Moderation", "gl.kick @user [reason]",               "Kick a member."),
    "ban":         ("Moderation", "gl.ban @user [del_days] [reason]",     "Ban a member."),
    "unban":       ("Moderation", "gl.unban <user_id> [reason]",          "Unban by user ID."),
    "softban":     ("Moderation", "gl.softban @user [reason]",            "Ban + unban to purge messages."),
    "massban":     ("Moderation", "gl.massban id1,id2 [reason]",          "Ban multiple users."),
    "masskick":    ("Moderation", "gl.masskick id1,id2 [reason]",         "Kick multiple members."),
    "clear":       ("Moderation", "gl.clear <amount> [@user]",            "Bulk delete messages."),
    "slowmode":    ("Moderation", "gl.slowmode <secs> [#channel]",        "Set slowmode. 0 to disable."),
    "lock":        ("Moderation", "gl.lock [#channel] [reason]",          "Lock a channel."),
    "unlock":      ("Moderation", "gl.unlock [#channel] [reason]",        "Unlock a channel."),
    "nick":        ("Moderation", "gl.nick @user [nickname]",             "Change or reset a nickname."),
    "role_add":    ("Moderation", "gl.role_add @user @role",              "Add a role to a member."),
    "role_remove": ("Moderation", "gl.role_remove @user @role",           "Remove a role from a member."),
    "nuke":        ("Moderation", "gl.nuke [#channel] [reason]",          "Delete and recreate a channel."),
    # Economy
    "balance":     ("Economy", "gl.balance [@user]",         "Check wallet and bank balance."),
    "money":       ("Economy", "gl.money [@user]",           "Alias for gl.balance."),
    "deposit":     ("Economy", "gl.deposit <amount|all>",    "Deposit coins to bank."),
    "withdraw":    ("Economy", "gl.withdraw <amount|all>",   "Withdraw coins from bank."),
    "give":        ("Economy", "gl.give @user <amount>",     "Send coins to another member."),
    "leaderboard": ("Economy", "gl.leaderboard",             "Top 10 richest members."),
    "net_worth":   ("Economy", "gl.net_worth [@user]",       "Full balance breakdown."),
    "work":        ("Economy", "gl.work",                    "Work for coins. 1 min cooldown."),
    "crime":       ("Economy", "gl.crime",                   "Commit a crime. 2h cooldown."),
    "rob":         ("Economy", "gl.rob @user",               "Rob a member's wallet."),
    "claim":       ("Economy", "gl.claim",                   "Daily reward. 24h cooldown."),
    "fish":        ("Economy", "gl.fish",                    "Go fishing. 30 min cooldown."),
    "hunt":        ("Economy", "gl.hunt",                    "Go hunting. 45 min cooldown."),
    "mine":        ("Economy", "gl.mine",                    "Mine for gems. 1h cooldown."),
    "chop":        ("Economy", "gl.chop",                    "Chop wood. 45 min cooldown."),
    "beg":         ("Economy", "gl.beg",                     "Beg for coins. 5 min cooldown."),
    "btc":         ("Economy", "gl.btc",                     "Convert Bitcoin to GL coins."),
    # Games
    "blackjack":   ("Games", "gl.blackjack <bet>",           "Play blackjack."),
    "slots":       ("Games", "gl.slots <bet>",               "Spin the slot machine."),
    "roulette":    ("Games", "gl.roulette <bet> <choice>",   "Bet on red/black/number."),
    "coinflip":    ("Games", "gl.coinflip <bet> <h/t>",      "Flip a coin."),
    "crash":       ("Games", "gl.crash <bet> <cashout>",     "Crash game."),
    "fight":       ("Games", "gl.fight <bet>",               "Rooster fight."),
    "roll":        ("Games", "gl.roll <bet> <high/low/num>", "Dice roll."),
    "pick":        ("Games", "gl.pick <bet> <1-10>",         "Pick a number."),
    # Stocks
    "stock_prices":    ("Stocks", "gl.stock_prices",              "View real stock prices."),
    "stock_buy":       ("Stocks", "gl.stock_buy <ticker> <qty>",  "Buy shares."),
    "stock_sell":      ("Stocks", "gl.stock_sell <ticker> <qty>", "Sell shares."),
    "stock_portfolio": ("Stocks", "gl.stock_portfolio [@user]",   "View portfolio."),
    "market_crash":    ("Stocks", "gl.market_crash <pct> [#ch]",  "Admin: crash all stocks."),
    "market_recover":  ("Stocks", "gl.market_recover",            "Admin: lift crash."),
    # Store
    "store":        ("Store", "gl.store",                    "View the item store."),
    "buy":          ("Store", "gl.buy <item_id>",            "Buy an item."),
    "sell":         ("Store", "gl.sell <item_id>",           "Sell an item back."),
    "inventory":    ("Store", "gl.inventory [@user]",        "View inventory."),
    "use_item":     ("Store", "gl.use_item <item_id>",       "Use an item."),
    "store_list":   ("Store", "gl.store_list <item_id> <price>", "List an item for sale."),
    "store_delist": ("Store", "gl.store_delist <listing_id>","Remove your listing."),
    # Fun
    "meme":              ("Fun", "gl.meme",                     "Random meme from r/memes."),
    "fact":              ("Fun", "gl.fact",                     "Random fact from r/facts."),
    "joke":              ("Fun", "gl.joke",                     "Random joke."),
    "would_you_rather":  ("Fun", "gl.wyr",                      "Would you rather..."),
    "truth_or_dare":     ("Fun", "gl.tod <truth|dare>",         "Truth or dare."),
    "ship":              ("Fun", "gl.ship @user1 @user2",        "Compatibility test."),
    "rate":              ("Fun", "gl.rate <thing>",              "Rate anything out of 10."),
    "rps":               ("Fun", "gl.rps <rock|paper|scissors>","Rock paper scissors."),
    "reverse":           ("Fun", "gl.reverse <text>",           "Reverse text."),
    "mock":              ("Fun", "gl.mock <text>",              "MoCkS tExT."),
    "emojify":           ("Fun", "gl.emojify <text>",           "🇪 🇲 🇴 🇯 🇮 🇫 🇾 text."),
    # Utility
    "avatar":   ("Utility", "gl.avatar [@user] [server|global]", "View full-size avatar."),
    "banner":   ("Utility", "gl.banner [@user]",                  "View profile banner."),
    "ping":     ("Utility", "gl.ping",                            "Check bot latency."),
    "8ball":    ("Utility", "gl.8ball <question>",                "Magic 8 ball."),
    "poll":     ("Utility", "gl.poll <question> | opt1 | opt2",  "Create a poll."),
    "afk":      ("Utility", "gl.afk [reason]",                   "Set AFK status."),
    "remind":   ("Utility", "gl.remind <duration> <message>",    "Set a reminder."),
    "search":   ("Utility", "gl.search <query>",                 "Search via DuckDuckGo."),
    "say":      ("Utility", "gl.say #channel <message>",         "Admin: make bot say something."),
    "embed":    ("Utility", "gl.embed #channel <title> | <desc>","Admin: send custom embed."),
    # Tickets
    "ticket_setup":  ("Tickets", "gl.ticket_setup",  "Setup ticket system."),
    "ticket_config": ("Tickets", "gl.ticket_config", "View ticket settings."),
    # Welcome
    "welcome_setup":   ("Welcome", "gl.welcome_setup #ch #ch [text]", "Configure welcome/leave."),
    "welcome_setext":  ("Welcome", "gl.welcome_setext <text>",        "Update welcome text."),
    "welcome_test":    ("Welcome", "gl.welcome_test",                 "Preview welcome message."),
    "welcome_config":  ("Welcome", "gl.welcome_config",               "View welcome settings."),
    "welcome_disable": ("Welcome", "gl.welcome_disable <welcome|leave|both>", "Disable messages."),
    # Info
    "userinfo":        ("Info", "gl.userinfo [@user]",  "Full member profile."),
    "serverinfo":      ("Info", "gl.serverinfo",        "Server stats."),
    "botinfo":         ("Info", "gl.botinfo",           "Bot stats and uptime."),
    "about":           ("Info", "gl.about",             "About Global League Bot."),
    "antiraid_setup":  ("Info", "gl.antiraid_setup",    "Configure anti-raid."),
    "antiraid_status": ("Info", "gl.antiraid_status",   "Anti-raid status."),
    "antiraid_unlock": ("Info", "gl.antiraid_unlock",   "Lift raid lockdown."),
    # Setup
    "setup":         ("Setup", "gl.setup",                          "Configure the bot."),
    "config":        ("Setup", "gl.config",                         "View configuration."),
    "perm_override": ("Setup", "gl.perm_override @role <cmd> <T/F>","Set permission override."),
    # Economy Admin
    "add_money":        ("Economy Admin", "gl.add_money @user <amount>",   "Add coins to a user."),
    "remove_money":     ("Economy Admin", "gl.remove_money @user <amount>","Remove coins."),
    "set_money":        ("Economy Admin", "gl.set_money @user <amount>",   "Set wallet amount."),
    "reset_economy":    ("Economy Admin", "gl.reset_economy",              "Wipe all economy data."),
    "add_store_item":   ("Economy Admin", "gl.add_store_item <id> <name> <price>", "Add store item."),
    "remove_store_item":("Economy Admin", "gl.remove_store_item <item_id>","Remove store item."),
    "edit_store_item":  ("Economy Admin", "gl.edit_store_item <item_id>",  "Edit store item."),
    "set_currency":     ("Economy Admin", "gl.set_currency <sym> <name>",  "Set currency."),
    "set_start_balance":("Economy Admin", "gl.set_start_balance <amount>", "Set start balance."),
    "set_cooldown":     ("Economy Admin", "gl.set_cooldown <cmd> <secs>",  "Set command cooldown."),
    "set_payout":       ("Economy Admin", "gl.set_payout <cmd> <amount>",  "Set payout amount."),
    "economy_stats":    ("Economy Admin", "gl.economy_stats",              "Economy statistics."),
    "money_audit_log":  ("Economy Admin", "gl.money_audit_log [@user]",    "Transaction history."),
    # Election
    "election_create":  ("Election", "gl.election_create <title> <c1> <c2> ...", "Create election."),
    "election_vote":    ("Election", "gl.election_vote",                          "Vote in election."),
    "election_results": ("Election", "gl.election_results",                       "Live results."),
    "election_end":     ("Election", "gl.election_end",                           "End election."),
    "election_cancel":  ("Election", "gl.election_cancel",                        "Cancel election."),
}

CATEGORIES = ["Moderation", "Economy", "Games", "Stocks", "Store", "Fun",
               "Utility", "Tickets", "Welcome", "Info", "Setup", "Economy Admin", "Election"]

CATEGORY_COLORS = {
    "Moderation":    0x9B59B6,
    "Economy":       0xF1C40F,
    "Games":         0xE74C3C,
    "Stocks":        0x2ECC71,
    "Store":         0x3498DB,
    "Fun":           0xFF5733,
    "Utility":       0x95A5A6,
    "Tickets":       0x5865F2,
    "Welcome":       0x2ECC71,
    "Info":          0x3498DB,
    "Setup":         0x9B59B6,
    "Economy Admin": 0xE67E22,
    "Election":      0x5865F2,
}


class HelpCog(commands.Cog, name="Help"):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    @commands.guild_only()
    async def help(self, ctx, *, query: str = None):
        """Show help. Usage: gl.help | gl.help <command> | gl.help <category>"""

        # Single command lookup
        if query:
            q = query.lower().strip()

            # Check if it's a command
            if q in COMMANDS:
                cat, usage, desc = COMMANDS[q]
                e = discord.Embed(title=f"📖 gl.{q}", color=CATEGORY_COLORS.get(cat, 0x5865F2))
                e.add_field(name="Usage",       value=f"`{usage}`", inline=False)
                e.add_field(name="Description", value=desc,         inline=False)
                e.add_field(name="Category",    value=cat,          inline=True)
                e.set_footer(text="[ ] = optional  •  < > = required")
                await ctx.send(embed=e)
                return

            # Check if it's a category
            cat_match = next((c for c in CATEGORIES if c.lower() == q), None)
            if cat_match:
                cmds = [(k, v[1], v[2]) for k, v in COMMANDS.items() if v[0] == cat_match]
                e = discord.Embed(
                    title=f"📂 {cat_match} Commands",
                    color=CATEGORY_COLORS.get(cat_match, 0x5865F2),
                )
                for name, usage, desc in cmds:
                    e.add_field(name=f"`{usage}`", value=desc, inline=False)
                e.set_footer(text="gl.help <command> for detailed help")
                await ctx.send(embed=e)
                return

            await ctx.send(f"❌ No command or category found for `{query}`. Use `gl.help` to see all.")
            return

        # Main help overview
        e = discord.Embed(
            title="🌐 Global League Bot — Help",
            description=(
                "**Prefix:** `gl.`\n"
                "**Usage:** `gl.help <command>` for details on any command\n"
                "**Example:** `gl.help ban` | `gl.help Economy`\n"
            ),
            color=0x5865F2,
        )
        for cat in CATEGORIES:
            cmds  = [k for k, v in COMMANDS.items() if v[0] == cat]
            names = " ".join(f"`{c}`" for c in cmds[:8])
            if len(cmds) > 8:
                names += f" *+{len(cmds) - 8} more*"
            e.add_field(name=f"{cat} ({len(cmds)})", value=names or "—", inline=False)

        e.set_footer(text=f"Total commands: {len(COMMANDS)}  •  gl.help <category> to browse")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
