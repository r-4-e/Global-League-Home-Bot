"""
cogs/search.py — DuckDuckGo search command for Elura.

Uses DuckDuckGo's free Instant Answer API (no API key required).
Results are public (ephemeral=False) so everyone in the channel sees them.
"""

from __future__ import annotations

import logging
from typing import Optional

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
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def cog_unload(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

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

        try:
            session = await self._get_session()
            params = {
                "q":              query,
                "format":         "json",
                "no_html":        "1",
                "skip_disambig":  "1",
                "no_redirect":    "1",
            }
            async with session.get(DDGO_API, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        embed=self._error_embed("DuckDuckGo returned an error. Try again later."),
                    )
                    return
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            log.error("search request failed: %s", exc)
            await interaction.followup.send(
                embed=self._error_embed("Could not reach DuckDuckGo. Try again later."),
            )
            return

        # ── Build embed ───────────────────────────────────────────────────
        e = discord.Embed(
            color=0xDE5833,  # DuckDuckGo orange
        )
        e.set_author(
            name=f"🔍 {query}",
            icon_url="https://duckduckgo.com/favicon.ico",
        )

        # Instant answer / abstract
        abstract     = data.get("AbstractText", "")
        abstract_url = data.get("AbstractURL",  "")
        abstract_src = data.get("AbstractSource", "")
        definition   = data.get("Definition", "")
        definition_src = data.get("DefinitionSource", "")
        answer       = data.get("Answer", "")
        image        = data.get("Image", "")

        # Instant calculation / direct answer (e.g. "2+2")
        if answer:
            e.title = "⚡ Instant Answer"
            e.description = str(answer)

        # Definition (dictionary lookups)
        elif definition:
            e.title = f"📖 Definition"
            e.description = definition
            if definition_src:
                e.set_footer(text=f"Source: {definition_src}")

        # Abstract from Wikipedia etc.
        elif abstract:
            e.title = abstract_src or "Result"
            e.description = abstract[:1000] + ("…" if len(abstract) > 1000 else "")
            if abstract_url:
                e.url = abstract_url
            if abstract_src:
                e.set_footer(text=f"Source: {abstract_src}")
            if image and image.startswith("http"):
                e.set_thumbnail(url=image)

        # Related topics fallback
        else:
            topics = data.get("RelatedTopics", [])
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
                # Pure fallback — link to DuckDuckGo search page
                e.title = "No instant results found"
                e.description = (
                    f"No instant answer found. "
                    f"[Click here to see full results](https://duckduckgo.com/?q={query.replace(' ', '+')})"
                )

        # Always include a "Full results" link at the bottom
        ddg_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
        current = e.description or ""
        if ddg_url not in current:
            e.add_field(name="🔗 Full Results", value=f"[Search DuckDuckGo]({ddg_url})", inline=False)

        e.set_footer(text=f"Requested by {interaction.user}  •  Powered by DuckDuckGo")
        await interaction.followup.send(embed=e)

    # ── Error embed ───────────────────────────────────────────────────────

    def _error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(
            title="❌ Search Failed",
            description=message,
            color=0xE74C3C,
        )

    # ── Error handler ─────────────────────────────────────────────────────

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("SearchCog error: %s", error)
        msg = "❌ Something went wrong with the search. Try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=self._error_embed(msg))
            else:
                await interaction.response.send_message(embed=self._error_embed(msg))
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
