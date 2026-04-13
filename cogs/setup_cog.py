"""
cogs/setup_cog.py — Setup commands. Prefix: gl.
"""
from __future__ import annotations
import logging
import discord
from discord.ext import commands
from config import GUILD_ID
from database import db
from utils import embeds
from utils.cache import guild_config_cache, automod_rules_cache
from utils.permissions import check_invoker_permission

log = logging.getLogger(__name__)

class SetupCog(commands.Cog, name="Setup"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setup")
    @commands.guild_only()
    async def setup(self, ctx):
        """Interactive setup. Usage: gl.setup"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return

        def check(m): return m.author == ctx.author and m.channel == ctx.channel

        await ctx.send("⚙️ **Setup Wizard** — Type `cancel` at any time to stop.\n\n**Step 1/4:** Mention the log channel (e.g. #logs)")
        try:
            m = await self.bot.wait_for("message", check=check, timeout=60)
            if m.content.lower() == "cancel": await ctx.send("Setup cancelled."); return
            log_channel = m.channel_mentions[0] if m.channel_mentions else None
            if not log_channel: await ctx.send("❌ No channel found. Setup cancelled."); return

            await ctx.send("**Step 2/4:** Mention the muted role (or type `skip`)")
            m = await self.bot.wait_for("message", check=check, timeout=60)
            if m.content.lower() == "cancel": await ctx.send("Setup cancelled."); return
            muted_role = m.role_mentions[0] if m.role_mentions else None

            await ctx.send("**Step 3/4:** Mention the staff role (or type `skip`)")
            m = await self.bot.wait_for("message", check=check, timeout=60)
            if m.content.lower() == "cancel": await ctx.send("Setup cancelled."); return
            staff_role = m.role_mentions[0] if m.role_mentions else None

            await ctx.send("**Step 4/4:** Enable AutoMod? Type `yes` or `no`")
            m = await self.bot.wait_for("message", check=check, timeout=60)
            if m.content.lower() == "cancel": await ctx.send("Setup cancelled."); return
            automod = m.content.lower() in ("yes", "y")

        except TimeoutError:
            await ctx.send("❌ Setup timed out."); return

        await db.upsert_guild_config({
            "guild_id":        ctx.guild.id,
            "log_channel_id":  log_channel.id,
            "muted_role_id":   muted_role.id if muted_role else None,
            "staff_role_id":   staff_role.id if staff_role else None,
            "automod_enabled": automod,
            "setup_complete":  True,
        })
        guild_config_cache.invalidate(f"log_ch_{ctx.guild.id}")
        automod_rules_cache.invalidate("rules")

        e = discord.Embed(title="✅ Setup Complete!", color=0x2ECC71)
        e.add_field(name="Log Channel", value=log_channel.mention,                                  inline=True)
        e.add_field(name="Muted Role",  value=muted_role.mention if muted_role else "Not set",      inline=True)
        e.add_field(name="Staff Role",  value=staff_role.mention if staff_role else "Not set",      inline=True)
        e.add_field(name="AutoMod",     value="✅ Enabled" if automod else "❌ Disabled",            inline=True)
        await ctx.send(embed=e)

    @commands.command(name="config")
    @commands.guild_only()
    async def config(self, ctx):
        """View current server configuration."""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        cfg = await db.get_guild_config(ctx.guild.id)
        if not cfg:
            await ctx.send("❌ Not configured. Run `gl.setup` first."); return
        lc = cfg.get("log_channel_id"); mr = cfg.get("muted_role_id"); sr = cfg.get("staff_role_id")
        e = discord.Embed(title="⚙️ Current Configuration", color=0x3498DB)
        e.add_field(name="Log Channel",    value=f"<#{lc}>" if lc else "Not set", inline=True)
        e.add_field(name="Muted Role",     value=f"<@&{mr}>" if mr else "Not set", inline=True)
        e.add_field(name="Staff Role",     value=f"<@&{sr}>" if sr else "Not set", inline=True)
        e.add_field(name="AutoMod",        value="✅ Enabled" if cfg.get("automod_enabled") else "❌ Disabled", inline=True)
        e.add_field(name="Setup Complete", value="✅ Yes" if cfg.get("setup_complete") else "❌ No", inline=True)
        e.timestamp = discord.utils.utcnow()
        await ctx.send(embed=e)

    @commands.command(name="perm_override")
    @commands.guild_only()
    async def perm_override(self, ctx, role: discord.Role, command: str, allowed: bool):
        """Set permission override. Usage: gl.perm_override @role <command> <true/false>"""
        ok, msg = check_invoker_permission(ctx, "administrator")
        if not ok: await ctx.send(msg); return
        success = await db.set_permission_override(
            role_id=role.id, command=command.lower().strip(),
            allowed=allowed, guild_id=ctx.guild.id,
        )
        if success:
            state = "✅ allowed" if allowed else "❌ denied"
            await ctx.send(embed=embeds.success("Override Set",
                    f"{role.mention} is now {state} to use `gl.{command.lower().strip()}`."))
        else:
            await ctx.send(embed=embeds.error("Failed", "Could not save override."))

async def setup(bot):
    await bot.add_cog(SetupCog(bot))
