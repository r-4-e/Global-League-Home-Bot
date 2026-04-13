"""
cogs/utility.py — Utility commands. Prefix: gl.
"""
from __future__ import annotations
import asyncio, logging, random
from datetime import datetime, timezone
import discord
from discord.ext import commands
from config import GUILD_ID
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)
_afk_store: dict[int, dict[int, str]] = {}

def _parse_duration(s):
    unit_map = {"s":1,"m":60,"h":3600,"d":86400}
    if not s: return None
    unit = s[-1].lower()
    if unit not in unit_map: return None
    try: return int(s[:-1]) * unit_map[unit]
    except ValueError: return None

class UtilityCog(commands.Cog, name="Utility"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check bot latency."""
        latency = round(self.bot.latency * 1000)
        color = 0x2ECC71 if latency < 100 else (0xF39C12 if latency < 200 else 0xE74C3C)
        status = "🟢 Good" if latency < 100 else ("🟡 Okay" if latency < 200 else "🔴 High")
        e = discord.Embed(title="🏓 Pong!", color=color)
        e.add_field(name="Latency", value=f"**{latency}ms**", inline=True)
        e.add_field(name="Status",  value=status,              inline=True)
        await ctx.send(embed=e)

    @commands.command(name="avatar")
    async def avatar(self, ctx, user: discord.Member = None, avatar_type: str = "server"):
        """View full-size avatar. Usage: gl.avatar [@user] [server|global]"""
        target = user or ctx.author
        if avatar_type == "server" and isinstance(target, discord.Member) and target.guild_avatar:
            av, tag = target.guild_avatar, "Server Avatar"
        else:
            av, tag = target.avatar or target.default_avatar, "Global Avatar"
        formats = []
        if av.is_animated(): formats.append(f"[GIF]({av.with_format('gif').url})")
        formats += [f"[PNG]({av.with_format('png').url})", f"[JPG]({av.with_format('jpg').url})",
                    f"[WEBP]({av.with_format('webp').url})"]
        e = discord.Embed(title=f"🖼️ {target.display_name}'s {tag}",
                          description=" • ".join(formats), color=0x5865F2)
        e.set_image(url=av.with_size(1024).url)
        e.set_footer(text=f"User ID: {target.id}")
        await ctx.send(embed=e)

    @commands.command(name="banner")
    async def banner(self, ctx, user: discord.Member = None):
        """View a user's profile banner."""
        target = user or ctx.author
        async with ctx.typing():
            fetched = await self.bot.fetch_user(target.id)
        if not fetched.banner:
            await ctx.send(f"❌ **{target.display_name}** doesn't have a banner."); return
        banner = fetched.banner
        formats = []
        if banner.is_animated(): formats.append(f"[GIF]({banner.with_format('gif').url})")
        formats += [f"[PNG]({banner.with_format('png').url})", f"[WEBP]({banner.with_format('webp').url})"]
        e = discord.Embed(title=f"🖼️ {target.display_name}'s Banner",
                          description=" • ".join(formats), color=0x5865F2)
        e.set_image(url=banner.with_size(1024).url)
        await ctx.send(embed=e)

    @commands.command(name="8ball")
    async def eightball(self, ctx, *, question: str):
        """Ask the magic 8 ball. Usage: gl.8ball <question>"""
        responses = [
            ("🟢","It is certain."),("🟢","Without a doubt."),("🟢","Yes, definitely."),
            ("🟢","Most likely."),("🟢","Signs point to yes."),("🟡","Reply hazy, try again."),
            ("🟡","Ask again later."),("🟡","Cannot predict now."),("🔴","Don't count on it."),
            ("🔴","My reply is no."),("🔴","Very doubtful."),("🔴","Outlook not so good."),
        ]
        dot, answer = random.choice(responses)
        e = discord.Embed(title="🎱 Magic 8 Ball", color=0x2C3E50)
        e.add_field(name="❓ Question", value=question,        inline=False)
        e.add_field(name=f"{dot} Answer",  value=f"*{answer}*", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="poll")
    async def poll(self, ctx, *, args: str):
        """Create a poll. Usage: gl.poll Question | Option 1 | Option 2 | Option 3"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            await ctx.send("❌ Usage: `gl.poll Question | Option 1 | Option 2`"); return
        question = parts[0]
        options  = parts[1:5]
        emojis   = ["🇦","🇧","🇨","🇩"]
        e = discord.Embed(title=f"📊 {question}", color=0x3498DB)
        e.description = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options))
        e.set_footer(text=f"Poll by {ctx.author}")
        msg = await ctx.send(embed=e)
        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

    @commands.command(name="afk")
    async def afk(self, ctx, *, reason: str = "AFK"):
        """Set AFK status. Usage: gl.afk [reason]"""
        if ctx.guild.id not in _afk_store: _afk_store[ctx.guild.id] = {}
        _afk_store[ctx.guild.id][ctx.author.id] = reason
        await ctx.send(embed=discord.Embed(
            title="💤 AFK Set",
            description=f"You are now AFK: **{reason}**",
            color=0x95A5A6,
        ))

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        guild_id  = message.guild.id
        guild_afk = _afk_store.get(guild_id, {})
        if message.author.id in guild_afk:
            del guild_afk[message.author.id]
            try:
                await message.reply(embed=discord.Embed(
                    description="✅ Welcome back! AFK removed.", color=0x2ECC71), delete_after=5)
            except discord.Forbidden: pass
            return
        for mentioned in message.mentions:
            if mentioned.id in guild_afk:
                reason = guild_afk[mentioned.id]
                try:
                    await message.reply(embed=discord.Embed(
                        description=f"💤 **{mentioned.display_name}** is AFK: {reason}",
                        color=0x95A5A6), delete_after=8)
                except discord.Forbidden: pass

    @commands.command(name="remind")
    async def remind(self, ctx, duration: str, *, message: str):
        """Set a reminder. Usage: gl.remind <10m|2h|1d> <message>"""
        seconds = _parse_duration(duration)
        if not seconds or seconds <= 0:
            await ctx.send("❌ Use formats like `10s`, `5m`, `2h`, `1d`."); return
        if seconds > 86400 * 7:
            await ctx.send("❌ Max reminder duration is 7 days."); return
        await ctx.send(embed=discord.Embed(
            title="⏰ Reminder Set",
            description=f"I'll remind you in **{duration}**.\n> {message}",
            color=0x3498DB,
        ))
        asyncio.create_task(self._fire_reminder(ctx.author.id, ctx.channel.id, message, seconds))

    async def _fire_reminder(self, user_id, channel_id, message, seconds):
        await asyncio.sleep(seconds)
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel): return
        try:
            await channel.send(content=f"<@{user_id}>", embed=discord.Embed(
                title="⏰ Reminder!", description=message, color=0xF39C12,
            ))
        except discord.Forbidden: pass

    @commands.command(name="say")
    @commands.guild_only()
    async def say(self, ctx, channel: discord.TextChannel, *, message: str):
        """Admin: make bot send a message. Usage: gl.say #channel <message>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        try:
            await channel.send(message)
            await ctx.message.delete()
        except discord.Forbidden:
            await ctx.send(f"❌ Can't send messages in {channel.mention}.")

    @commands.command(name="embed")
    @commands.guild_only()
    async def embed_cmd(self, ctx, channel: discord.TextChannel, *, args: str):
        """Admin: send custom embed. Usage: gl.embed #channel Title | Description | #color"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        parts = [p.strip() for p in args.split("|")]
        title = parts[0] if parts else "Embed"
        desc  = parts[1] if len(parts) > 1 else ""
        color_str = parts[2].strip("#") if len(parts) > 2 else "5865F2"
        try: color = int(color_str, 16)
        except ValueError: color = 0x5865F2
        e = discord.Embed(title=title, description=desc, color=color)
        e.timestamp = datetime.now(timezone.utc)
        try:
            await channel.send(embed=e)
            await ctx.send(f"✅ Sent to {channel.mention}.", delete_after=3)
        except discord.Forbidden:
            await ctx.send(f"❌ Can't send messages in {channel.mention}.")

async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
