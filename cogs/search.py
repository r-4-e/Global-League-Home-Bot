"""
cogs/search.py — DuckDuckGo search command.
"""
from __future__ import annotations
import json, logging
import aiohttp
import discord
from discord.ext import commands
from config import GUILD_ID

log = logging.getLogger(__name__)
DDGO_API = "https://api.duckduckgo.com/"

class SearchCog(commands.Cog, name="Search"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="search")
    @commands.guild_only()
    async def search(self, ctx, *, query: str):
        """Search the web using DuckDuckGo. Usage: gl.search <query>"""
        async with ctx.typing():
            data = await self._fetch(query)
        if data is None:
            await ctx.send("❌ Could not reach DuckDuckGo. Try again later."); return
        await ctx.send(embed=self._build_embed(query, data, ctx.author))

    async def _fetch(self, query):
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(DDGO_API, params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": "GlobalLeagueBot/1.0"}) as resp:
                    if resp.status != 200: return None
                    return json.loads(await resp.text())
        except Exception as exc:
            log.error("DDG fetch error: %s", exc)
            return None

    def _build_embed(self, query, data, user):
        e = discord.Embed(color=0xDE5833)
        e.set_author(name=f"🔍 {query}", icon_url="https://duckduckgo.com/favicon.ico")
        e.set_footer(text=f"Requested by {user}  •  Powered by DuckDuckGo")
        answer = data.get("Answer",""); abstract = data.get("AbstractText","")
        abstract_url = data.get("AbstractURL",""); abstract_src = data.get("AbstractSource","")
        definition = data.get("Definition",""); image = data.get("Image","")
        topics = data.get("RelatedTopics",[])
        ddg_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
        if answer:
            e.title = "⚡ Instant Answer"; e.description = str(answer)
        elif definition:
            e.title = "📖 Definition"; e.description = definition
        elif abstract:
            e.title = abstract_src or "Result"
            e.description = abstract[:1000] + ("…" if len(abstract) > 1000 else "")
            if abstract_url: e.url = abstract_url
            if image and image.startswith("http"): e.set_thumbnail(url=image)
        else:
            results = []
            for t in topics:
                if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
                    results.append(f"[{t['Text'][:80]}]({t['FirstURL']})")
                if len(results) >= 4: break
            if results:
                e.title = "Related Results"; e.description = "\n\n".join(results)
            else:
                e.title = "No instant results"
                e.description = f"[Click here to see full results]({ddg_url})"
        e.add_field(name="🔗 Full Results", value=f"[Open DuckDuckGo]({ddg_url})", inline=False)
        return e

async def setup(bot):
    await bot.add_cog(SearchCog(bot))
