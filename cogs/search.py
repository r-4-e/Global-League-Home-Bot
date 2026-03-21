"""
cogs/search.py — DuckDuckGo search command for Elura.

Uses DuckDuckGo's free Instant Answer API (no API key required).
Results are public (ephemeral=False).
"""

from __future__ import annotations

import json
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID

log = logging.getLogger(__name__)

DDGO_API = "https://api.duckduckgo.com/"


class SearchCog(commands.Cog, name="Search"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /search ───────────────────────────────────────────────────────────

    @app_commands.command(name="search", description="Search the web using DuckDuckGo.")
    @app_commands.describe(query="What do you want to search for?")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        data = await self._fetch(query)

        if data is None:
            await interaction.followup.send(
                embed=self._error("Could not reach DuckDuckGo. Try again later.")
            )
            return

        embed = self._build_embed(query, data, interaction.user)
        await interaction.followup.send(embed=embed)

    # ── Fetch ─────────────────────────────────────────────────────────────

    async def _fetch(self, query: str) -> dict | None:
        params = {
            "q":             query,
            "format":        "json",
            "no_html":       "1",
            "skip_disambig": "1",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    DDGO_API,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": "Elura Discord Bot"},
                ) as resp:
                    if resp.status != 200:
                        log.error("DDG returned status %s", resp.status)
                        return None
                    text = await resp.text()
                    return json.loads(text)
        except Exception as exc:
            log.error("DDG fetch error: %s", exc)
            return None

    # ── Build embed ───────────────────────────────────────────────────────

    def _build_embed(self, query: str, data: dict, user: discord.User | discord.Member) -> discord.Embed:
        e = discord.Embed(color=0xDE5833)
        e.set_author(
            name=f"🔍 {query}",
            icon_url="https://duckduckgo.com/favicon.ico",
        )
        e.set_footer(text=f"Requested by {user}  •  Powered by DuckDuckGo")

        answer       = data.get("Answer", "")
        abstract     = data.get("AbstractText", "")
        abstract_url = data.get("AbstractURL", "")
        abstract_src = data.get("AbstractSource", "")
        definition   = data.get("Definition", "")
        def_src      = data.get("DefinitionSource", "")
        image        = data.get("Image", "")
        topics       = data.get("RelatedTopics", [])

        ddg_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"

        if answer:
            e.title = "⚡ Instant Answer"
            e.description = str(answer)

        elif definition:
            e.title = "📖 Definition"
            e.description = definition
            if def_src:
                e.set_footer(text=f"Source: {def_src}  •  Requested by {user}")

        elif abstract:
            e.title = abstract_src or "Result"
            e.description = abstract[:1000] + ("…" if len(abstract) > 1000 else "")
            if abstract_url:
                e.url = abstract_url
            if image and image.startswith("http"):
                e.set_thumbnail(url=image)

        else:
            results = []
            for t in topics:
                if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
                    results.append(f"[{t['Text'][:80]}]({t['FirstURL']})")
                if len(results) >= 4:
                    break

            if results:
                e.title = "Related Results"
                e.description = "\n\n".join(results)
            else:
                e.title = "No instant results found"
                e.description = f"[Click here to see full results on DuckDuckGo]({ddg_url})"

        e.add_field(name="🔗 Full Results", value=f"[Open DuckDuckGo]({ddg_url})", inline=False)
        return e

    # ── Error embed ───────────────────────────────────────────────────────

    def _error(self, message: str) -> discord.Embed:
        return discord.Embed(title="❌ Search Failed", description=message, color=0xE74C3C)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
