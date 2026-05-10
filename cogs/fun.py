"""
cogs/fun.py — Fun Commands for Global League Bot.

Commands:
  /meme           — random meme from r/memes
  /fact           — random fact from r/facts
  /joke           — random joke
  /botinfo        — Global League Bot stats
  /would_you_rather — two choices with live vote buttons
  /truth_or_dare  — random truth or dare
  /ship           — compatibility % between two members
  /rate           — rate anything out of 10
  /reverse        — reverse text
  /mock           — mOcK tExT
  /emojify        — 🇪 🇲 🇴 🇯 🇮 🇫 🇾
  /rps            — rock paper scissors
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID

log = logging.getLogger(__name__)

FACTS = [
    "Honey never spoils. Archaeologists found 3,000-year-old honey in Egyptian tombs that was still edible.",
    "A group of flamingos is called a flamboyance.",
    "Octopuses have three hearts and blue blood.",
    "Bananas are technically berries, but strawberries are not.",
    "A bolt of lightning contains enough energy to toast 100,000 slices of bread.",
    "Sharks are older than trees — they have existed for over 400 million years.",
    "Wombats produce cube-shaped droppings.",
    "A snail can sleep for 3 years.",
    "Cows have best friends and get stressed when separated from them.",
    "The dot over a lowercase i or j is called a tittle.",
]

JOKES = [
    ("Why don't scientists trust atoms?", "Because they make up everything!"),
    ("Why did the scarecrow win an award?", "Because he was outstanding in his field."),
    ("I told my wife she was drawing her eyebrows too high.", "She looked surprised."),
    ("Why can't you give Elsa a balloon?", "Because she'll let it go."),
    ("What do you call a fake noodle?", "An impasta."),
    ("Why did the bicycle fall over?", "Because it was two-tired."),
    ("What do you call cheese that isn't yours?", "Nacho cheese."),
    ("Why do cows wear bells?", "Because their horns don't work."),
    ("I'm reading a book about anti-gravity.", "It's impossible to put down."),
    ("What did the ocean say to the beach?", "Nothing, it just waved."),
    ("Why don't eggs tell jokes?", "They'd crack each other up."),
    ("What do you call a sleeping dinosaur?", "A dino-snore."),
    ("Why did the math book look so sad?", "Because it had too many problems."),
    ("What's a skeleton's least favourite room?", "The living room."),
    ("I used to hate facial hair.", "But then it grew on me."),
    ("Why did the golfer bring an extra pair of pants?", "In case he got a hole in one."),
    ("What do you call a can opener that doesn't work?", "A can't opener."),
    ("Why did the tomato turn red?", "Because it saw the salad dressing."),
]

TRUTHS = [
    "What's the most embarrassing thing you've ever done?",
    "What's your biggest fear?",
    "Have you ever lied to get out of trouble? What was it?",
    "What's the worst gift you've ever received?",
    "What's a secret you've never told anyone?",
    "Have you ever cheated on a test?",
    "What's the most childish thing you still do?",
    "Who was your first crush?",
    "What's something you're addicted to?",
    "What's the most trouble you've ever been in?",
    "Have you ever blamed someone else for something you did?",
    "What's the most ridiculous thing you've ever bought?",
]

DARES = [
    "Do your best impression of someone in this server.",
    "Send the last photo in your camera roll.",
    "Change your nickname to something embarrassing for 1 hour.",
    "Type the next message using only your elbows.",
    "Speak in rhymes for the next 5 minutes.",
    "Send a voice message saying 'I am a potato'.",
    "Tell everyone your most searched thing on Google this week.",
    "Send a DM to a random server member saying 'I respect you'.",
    "Set your status to something embarrassing for 30 minutes.",
    "Use only capital letters for the next 10 minutes.",
    "Write a haiku about the person to your left.",
]

WYR_OPTIONS = [
    ("Have the ability to fly", "Have the ability to be invisible"),
    ("Always speak the truth", "Always lie"),
    ("Be famous but hated", "Be unknown but loved"),
    ("Live without music", "Live without TV/movies"),
    ("Have unlimited money but no friends", "Have amazing friends but be broke"),
    ("Be able to speak every language", "Be able to play every instrument"),
    ("Live in the past", "Live in the future"),
    ("Have super strength", "Have super speed"),
    ("Eat only sweet food forever", "Eat only salty food forever"),
    ("Never use social media again", "Never watch another movie/show again"),
    ("Be 10 minutes late to everything", "Be 20 minutes early to everything"),
    ("Have a rewind button for your life", "Have a pause button for your life"),
    ("Know how you will die", "Know when you will die"),
    ("Be able to teleport anywhere", "Be able to time travel"),
    ("Lose all your memories", "Never be able to make new ones"),
]


def _err(t, d=""): return discord.Embed(title=f"❌ {t}", description=d, color=0xE74C3C)


# ---------------------------------------------------------------------------
# Would You Rather View
# ---------------------------------------------------------------------------

class WouldYouRatherView(discord.ui.View):
    def __init__(self, option_a: str, option_b: str) -> None:
        super().__init__(timeout=300)
        self.votes    = {"a": set(), "b": set()}
        self.option_a = option_a
        self.option_b = option_b

    def _build_embed(self) -> discord.Embed:
        total = len(self.votes["a"]) + len(self.votes["b"])
        pct_a = int(len(self.votes["a"]) / total * 100) if total else 0
        pct_b = int(len(self.votes["b"]) / total * 100) if total else 0
        e = discord.Embed(title="🤔 Would You Rather…", color=0x9B59B6)
        e.add_field(name=f"🅰️ {self.option_a}", value=f"{pct_a}% ({len(self.votes['a'])} votes)", inline=True)
        e.add_field(name=f"🅱️ {self.option_b}", value=f"{pct_b}% ({len(self.votes['b'])} votes)", inline=True)
        e.set_footer(text=f"Total votes: {total}")
        return e

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.primary,   emoji="🅰️")
    async def vote_a(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.votes["b"].discard(interaction.user.id)
        self.votes["a"].add(interaction.user.id)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.secondary, emoji="🅱️")
    async def vote_b(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.votes["a"].discard(interaction.user.id)
        self.votes["b"].add(interaction.user.id)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class FunCog(commands.Cog, name="Fun"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot   = bot
        self._start = datetime.now(timezone.utc)

    # ── /meme ─────────────────────────────────────────────────────────────

    @app_commands.command(name="meme", description="Fetch a random meme from r/memes.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def meme(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.reddit.com/r/memes/hot.json?limit=50",
                    headers={"User-Agent": "GlobalLeagueBot/1.0"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Reddit returned {resp.status}")
                    data = await resp.json()

            posts = data["data"]["children"]
            valid = [
                p["data"] for p in posts
                if not p["data"].get("stickied")
                and not p["data"].get("over_18")
                and p["data"].get("url", "").endswith((".jpg", ".jpeg", ".png", ".gif"))
            ]
            if not valid:
                raise ValueError("No valid posts")

            post = random.choice(valid)
            e    = discord.Embed(
                title=post["title"][:250],
                url=f"https://reddit.com{post['permalink']}",
                color=0xFF5700,
            )
            e.set_image(url=post["url"])
            e.set_footer(text=f"👍 {post['ups']:,}  •  r/memes")
            await interaction.followup.send(embed=e)

        except Exception as exc:
            log.error("meme fetch error: %s", exc)
            await interaction.followup.send(
                embed=_err("Failed", "Couldn't fetch a meme right now. Try again later."), ephemeral=True
            )

    # ── /fact ─────────────────────────────────────────────────────────────

    @app_commands.command(name="fact", description="Get a random fact from r/facts.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def fact(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.reddit.com/r/facts/hot.json?limit=50",
                    headers={"User-Agent": "GlobalLeagueBot/1.0"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Reddit returned {resp.status}")
                    data = await resp.json()

            posts = data["data"]["children"]
            valid = [
                p["data"] for p in posts
                if not p["data"].get("stickied")
                and not p["data"].get("over_18")
                and (p["data"].get("selftext") or p["data"].get("title"))
            ]
            if not valid:
                raise ValueError("No valid posts")

            post  = random.choice(valid)
            title = post["title"][:500]
            body  = post.get("selftext", "").strip()[:500]

            e = discord.Embed(
                title="🧠 Random Fact",
                url=f"https://reddit.com{post['permalink']}",
                color=0x3498DB,
            )
            e.description = f"**{title}**"
            if body:
                e.description += f"\n\n{body}"
            e.set_footer(text=f"👍 {post['ups']:,}  •  r/facts  •  Requested by {interaction.user}")
            await interaction.followup.send(embed=e)

        except Exception as exc:
            log.error("fact fetch error: %s", exc)
            chosen = random.choice(FACTS)
            e = discord.Embed(title="🧠 Random Fact", description=chosen, color=0x3498DB)
            e.set_footer(text=f"Requested by {interaction.user}")
            await interaction.followup.send(embed=e)

    # ── /joke ─────────────────────────────────────────────────────────────

    @app_commands.command(name="joke", description="Get a random joke.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def joke(self, interaction: discord.Interaction) -> None:
        setup, punchline = random.choice(JOKES)
        e = discord.Embed(title="😂 Joke", color=0xF1C40F)
        e.add_field(name="Setup",     value=setup,     inline=False)
        e.add_field(name="Punchline", value=punchline, inline=False)
        await interaction.response.send_message(embed=e)

    # ── /botinfo ──────────────────────────────────────────────────────────

    @app_commands.command(name="botinfo", description="View Global League Bot stats and info.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def botinfo(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot   = self.bot
        guild = interaction.guild
        now   = datetime.now(timezone.utc)
        delta = now - self._start
        days  = delta.days
        hours = delta.seconds // 3600
        mins  = (delta.seconds % 3600) // 60
        uptime    = f"{days}d {hours}h {mins}m"
        cmd_count = len(bot.tree.get_commands(guild=discord.Object(id=GUILD_ID)))
        latency   = round(bot.latency * 1000)

        e = discord.Embed(
            title="🌐 Global League Bot",
            description="The ultimate all-in-one bot for Global League.",
            color=0x5865F2,
        )
        if bot.user.avatar:
            e.set_thumbnail(url=bot.user.avatar.url)
        e.add_field(name="🤖 Bot Name",   value=str(bot.user),              inline=True)
        e.add_field(name="🆔 Bot ID",     value=f"`{bot.user.id}`",          inline=True)
        e.add_field(name="🏓 Latency",    value=f"{latency}ms",              inline=True)
        e.add_field(name="⏱ Uptime",      value=uptime,                      inline=True)
        e.add_field(name="📟 Commands",   value=str(cmd_count),              inline=True)
        e.add_field(name="👥 Members",    value=f"{guild.member_count:,}",   inline=True)
        e.add_field(name="💬 Channels",   value=str(len(guild.channels)),    inline=True)
        e.add_field(name="🎭 Roles",      value=str(len(guild.roles)),       inline=True)
        e.add_field(name="🐍 Library",    value="discord.py 2.x",            inline=True)
        e.set_footer(text=f"Requested by {interaction.user}  •  Global League Bot")
        e.timestamp = now
        await interaction.followup.send(embed=e)

    # ── /would_you_rather ─────────────────────────────────────────────────

    @app_commands.command(name="would_you_rather", description="Would you rather...?")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def would_you_rather(self, interaction: discord.Interaction) -> None:
        a, b  = random.choice(WYR_OPTIONS)
        view  = WouldYouRatherView(a, b)
        e     = discord.Embed(title="🤔 Would You Rather…", color=0x9B59B6)
        e.add_field(name="🅰️ Option A", value=a, inline=True)
        e.add_field(name="🅱️ Option B", value=b, inline=True)
        await interaction.response.send_message(embed=e, view=view)

    # ── /truth_or_dare ────────────────────────────────────────────────────

    @app_commands.command(name="truth_or_dare", description="Get a random truth or dare.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Truth", value="truth"),
        app_commands.Choice(name="Dare",  value="dare"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def truth_or_dare(self, interaction: discord.Interaction, choice: str) -> None:
        if choice == "truth":
            content, title, color = random.choice(TRUTHS), "🤫 Truth", 0x3498DB
        else:
            content, title, color = random.choice(DARES),  "🎯 Dare",  0xE74C3C
        e = discord.Embed(title=title, description=content, color=color)
        e.set_footer(text=f"Requested by {interaction.user}")
        await interaction.response.send_message(embed=e)

    # ── /ship ─────────────────────────────────────────────────────────────

    @app_commands.command(name="ship", description="Calculate compatibility between two members.")
    @app_commands.describe(user1="First member", user2="Second member")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ship(
        self,
        interaction: discord.Interaction,
        user1: discord.Member,
        user2: discord.Member,
    ) -> None:
        score = (user1.id * 7 + user2.id * 13) % 101

        if score >= 90:
            label, color, fill = "💍 Soulmates",      0xFF69B4, 10
        elif score >= 75:
            label, color, fill = "💘 Great Match",    0xFF5733, 8
        elif score >= 60:
            label, color, fill = "💖 Good Chemistry", 0xE74C3C, 6
        elif score >= 40:
            label, color, fill = "💛 Decent Pair",    0xF1C40F, 4
        elif score >= 20:
            label, color, fill = "💔 Unlikely Match", 0x95A5A6, 2
        else:
            label, color, fill = "🚫 Incompatible",   0x7F8C8D, 1

        bar      = "❤️" * fill + "🖤" * (10 - fill)
        half1    = user1.display_name[:len(user1.display_name) // 2]
        half2    = user2.display_name[len(user2.display_name) // 2:]
        shipname = f"{half1}{half2}"

        e = discord.Embed(title="💞 Compatibility Test", color=color)
        e.add_field(name="Couple",     value=f"{user1.mention} ❤️ {user2.mention}", inline=False)
        e.add_field(name="Ship Name",  value=f"**{shipname}**",                      inline=True)
        e.add_field(name="Score",      value=f"**{score}%**",                        inline=True)
        e.add_field(name="Verdict",    value=label,                                  inline=True)
        e.add_field(name="Love Meter", value=bar,                                    inline=False)
        await interaction.response.send_message(embed=e)

    # ── /rate ─────────────────────────────────────────────────────────────

    @app_commands.command(name="rate", description="Get a bot rating out of 10 for anything.")
    @app_commands.describe(thing="A user, object, or concept to rate")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def rate(self, interaction: discord.Interaction, thing: str) -> None:
        score = sum(ord(c) for c in thing.lower()) % 11

        if score == 10:
            verdict, color = "Absolutely perfect. A legend.",       0xF1C40F
        elif score >= 8:
            verdict, color = "Genuinely impressive.",               0x2ECC71
        elif score >= 6:
            verdict, color = "Pretty solid, not bad at all.",       0x3498DB
        elif score >= 4:
            verdict, color = "Average. Room for improvement.",      0xF39C12
        elif score >= 2:
            verdict, color = "Could be better. Much better.",       0xE67E22
        else:
            verdict, color = "Absolutely terrible. I'm sorry.",     0xE74C3C

        stars = "⭐" * score + "☆" * (10 - score)
        e = discord.Embed(title="⭐ Rating", color=color)
        e.add_field(name="Subject", value=thing,             inline=False)
        e.add_field(name="Score",   value=f"**{score}/10**", inline=True)
        e.add_field(name="Stars",   value=stars,             inline=False)
        e.add_field(name="Verdict", value=verdict,           inline=False)
        e.set_footer(text="Rated by Global League Bot")
        await interaction.response.send_message(embed=e)

    # ── /reverse ──────────────────────────────────────────────────────────

    @app_commands.command(name="reverse", description="Reverse your text.")
    @app_commands.describe(text="Text to reverse")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def reverse(self, interaction: discord.Interaction, text: str) -> None:
        e = discord.Embed(title="🔄 Reversed", color=0x3498DB)
        e.add_field(name="Original", value=text,       inline=False)
        e.add_field(name="Reversed", value=text[::-1], inline=False)
        await interaction.response.send_message(embed=e)

    # ── /mock ─────────────────────────────────────────────────────────────

    @app_commands.command(name="mock", description="MoCkS yOuR tExT.")
    @app_commands.describe(text="Text to mock")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def mock(self, interaction: discord.Interaction, text: str) -> None:
        mocked = "".join(
            c.upper() if i % 2 == 0 else c.lower()
            for i, c in enumerate(text)
        )
        e = discord.Embed(title="🐔 Mocked", color=0xF39C12)
        e.add_field(name="Original", value=text,   inline=False)
        e.add_field(name="Mocked",   value=mocked, inline=False)
        await interaction.response.send_message(embed=e)

    # ── /emojify ──────────────────────────────────────────────────────────

    @app_commands.command(name="emojify", description="Convert text to emoji letters.")
    @app_commands.describe(text="Text to emojify")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def emojify(self, interaction: discord.Interaction, text: str) -> None:
        emoji_map = {
            "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
            "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
            "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
            "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
            "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾",
            "z": "🇿", "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣",
            "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣",
            "9": "9️⃣", " ": "  ",
        }
        result = " ".join(emoji_map.get(c.lower(), c) for c in text)
        if len(result) > 1000:
            await interaction.response.send_message(
                embed=_err("Too Long", "Your text is too long to emojify. Try something shorter."),
                ephemeral=True,
            )
            return
        e = discord.Embed(title="🔤 Emojified", color=0x2ECC71)
        e.add_field(name="Original", value=text,   inline=False)
        e.add_field(name="Result",   value=result, inline=False)
        await interaction.response.send_message(embed=e)

    # ── /rps ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rps", description="Play rock paper scissors against the bot.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🪨 Rock",     value="rock"),
        app_commands.Choice(name="📄 Paper",    value="paper"),
        app_commands.Choice(name="✂️ Scissors", value="scissors"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def rps(self, interaction: discord.Interaction, choice: str) -> None:
        options  = ["rock", "paper", "scissors"]
        emojis   = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        bot_pick = random.choice(options)
        wins     = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

        if choice == bot_pick:
            result, color = "🤝 It's a tie!", 0xF1C40F
        elif wins[choice] == bot_pick:
            result, color = "🎉 You win!", 0x2ECC71
        else:
            result, color = "😈 Bot wins!", 0xE74C3C

        e = discord.Embed(title="🎮 Rock Paper Scissors", color=color)
        e.add_field(name="Your Pick", value=f"{emojis[choice]} {choice.capitalize()}",   inline=True)
        e.add_field(name="Bot Pick",  value=f"{emojis[bot_pick]} {bot_pick.capitalize()}", inline=True)
        e.add_field(name="Result",    value=result,                                        inline=False)
        await interaction.response.send_message(embed=e)

    # ── Error handler ──────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("FunCog error: %s", error)
        msg = "❌ Something went wrong. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=_err("Error", msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=_err("Error", msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
