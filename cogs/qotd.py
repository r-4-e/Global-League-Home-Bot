"""
cogs/qotd.py — Question of the Day for Elura

Auto-posts a daily question at a configured time. Questions come from a
staff-managed bank stored in Supabase. Each question gets a thread
auto-created under it so answers don't flood the channel.

Commands (staff only):
    gl.qotd add <question>      — add a question to the bank
    gl.qotd remove <id>         — remove a question by ID
    gl.qotd list                — list all pending questions
    gl.qotd preview             — show what posts next
    gl.qotd post                — force-post right now
    gl.qotd setchannel #ch      — set the QOTD channel
    gl.qotd setrole @role       — set the ping role
    gl.qotd settime HH:MM       — set daily post time (UTC, 24h)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, time as dtime

import discord
from discord.ext import commands, tasks
from discord import app_commands

import config
from database import db

log = logging.getLogger("elura.qotd")

DEFAULT_QUESTIONS = [
    "If you could sign any player in the world right now, who would it be and why?",
    "What's the most memorable match you've ever watched?",
    "Who do you think will win the championship this season?",
    "What's your hottest take in football right now?",
    "If you were a manager for a day, what's the first change you'd make?",
    "Who's the most underrated player in the league right now?",
    "What's the best goal you've ever seen scored?",
    "Which club has the best fans in the world?",
    "If you could bring back one retired player, who would it be?",
    "What's your favourite football memory of all time?",
]


class QOTD(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._daily_loop_started = False

    async def cog_load(self) -> None:
        await db.ensure_qotd_config()
        self.daily_qotd.start()
        log.info("QOTD cog loaded, daily loop started.")

    def cog_unload(self) -> None:
        self.daily_qotd.cancel()

    # ── Daily loop ────────────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def daily_qotd(self) -> None:
        cfg = await db.get_qotd_config()
        if not cfg:
            return

        channel_id = cfg.get("channel_id")
        post_time_str = cfg.get("post_time", "09:00")
        if not channel_id:
            return

        try:
            h, m = map(int, post_time_str.split(":"))
            target = dtime(h, m, 0)
        except (ValueError, AttributeError):
            target = dtime(9, 0, 0)

        now = datetime.now(timezone.utc)
        current_time = dtime(now.hour, now.minute, 0)

        if current_time != target:
            return

        # Check we haven't already posted today
        last_posted = cfg.get("last_posted_date")
        today = now.strftime("%Y-%m-%d")
        if last_posted == today:
            return

        await self._post_qotd(channel_id, cfg.get("ping_role_id"))
        await db.set_qotd_last_posted(today)

    @daily_qotd.before_loop
    async def before_daily_qotd(self) -> None:
        await self.bot.wait_until_ready()

    # ── Core post logic ───────────────────────────────────────────────────────
    async def _post_qotd(self, channel_id: int, ping_role_id: int | None = None) -> bool:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            log.warning("QOTD channel %s not found.", channel_id)
            return False

        question_row = await db.get_next_qotd_question()
        if question_row:
            question = question_row["question"]
            question_id = question_row["id"]
            await db.mark_qotd_used(question_id)
            is_default = False
        else:
            # Bank empty — pick a random default
            import random
            question = random.choice(DEFAULT_QUESTIONS)
            is_default = True

        now = datetime.now(timezone.utc)
        day_num = await db.increment_qotd_day_counter()

        embed = discord.Embed(
            title=f"❓ Question of the Day #{day_num}",
            description=f"**{question}**",
            color=config.COLOR_INFO,
        )
        embed.set_footer(
            text=f"📅 {now.strftime('%A, %d %B %Y')} • Drop your answer below!"
        )

        content = None
        if ping_role_id:
            role = channel.guild.get_role(ping_role_id)
            if role:
                content = role.mention

        try:
            msg = await channel.send(content=content, embed=embed)
            await msg.add_reaction("🤔")
            # Auto-create a thread so answers stay tidy
            await msg.create_thread(
                name=f"QOTD #{day_num} — Answers",
                auto_archive_duration=1440,  # 24h
            )
            if is_default:
                log.info("QOTD posted using default question (bank empty).")
            else:
                log.info("QOTD #%s posted: %s", day_num, question[:60])
            return True
        except discord.Forbidden:
            log.error("Missing permissions to post QOTD in channel %s.", channel_id)
            return False
        except discord.HTTPException as exc:
            log.error("Failed to post QOTD: %s", exc)
            return False

    # ── Staff command group ───────────────────────────────────────────────────
    @commands.group(
        name="qotd",
        invoke_without_command=True,
        case_insensitive=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def qotd_group(self, ctx: commands.Context) -> None:
        cfg = await db.get_qotd_config()
        channel_id = cfg.get("channel_id") if cfg else None
        post_time = cfg.get("post_time", "09:00") if cfg else "09:00"
        ping_role_id = cfg.get("ping_role_id") if cfg else None
        pending = await db.count_qotd_questions()
        day_num = cfg.get("day_counter", 0) if cfg else 0

        channel_mention = f"<#{channel_id}>" if channel_id else "Not set"
        role_mention = f"<@&{ping_role_id}>" if ping_role_id else "Not set"

        embed = discord.Embed(title="QOTD Settings", color=config.COLOR_INFO)
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="Post Time (UTC)", value=post_time, inline=True)
        embed.add_field(name="Ping Role", value=role_mention, inline=True)
        embed.add_field(name="Questions in bank", value=str(pending), inline=True)
        embed.add_field(name="Total posted", value=str(day_num), inline=True)
        await ctx.send(embed=embed)

    @qotd_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def qotd_add(self, ctx: commands.Context, *, question: str) -> None:
        """Add a question to the bank."""
        if len(question) > 500:
            await ctx.send("❌ Question too long (max 500 characters).", ephemeral=True)
            return
        qid = await db.add_qotd_question(question, ctx.author.id)
        if qid:
            await ctx.send(f"✅ Question added to the bank (ID: `{qid}`).")
        else:
            await ctx.send("❌ Failed to add question. Try again.")

    @qotd_group.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def qotd_remove(self, ctx: commands.Context, question_id: int) -> None:
        """Remove a question by its ID."""
        ok = await db.remove_qotd_question(question_id)
        if ok:
            await ctx.send(f"✅ Question `{question_id}` removed.")
        else:
            await ctx.send(f"❌ No question found with ID `{question_id}`.")

    @qotd_group.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def qotd_list(self, ctx: commands.Context) -> None:
        """List all pending questions in the bank."""
        questions = await db.list_qotd_questions()
        if not questions:
            await ctx.send("📭 The question bank is empty. Add some with `gl.qotd add <question>`.")
            return

        # Paginate into chunks of 10
        lines = [f"`{q['id']}` — {q['question'][:80]}{'...' if len(q['question']) > 80 else ''}" for q in questions]
        chunks = [lines[i:i+10] for i in range(0, len(lines), 10)]

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"QOTD Bank ({len(questions)} questions) — Page {i+1}/{len(chunks)}",
                description="\n".join(chunk),
                color=config.COLOR_INFO,
            )
            await ctx.send(embed=embed)

    @qotd_group.command(name="preview")
    @commands.has_permissions(manage_guild=True)
    async def qotd_preview(self, ctx: commands.Context) -> None:
        """Preview the next question that will be posted."""
        question_row = await db.get_next_qotd_question()
        if not question_row:
            await ctx.send("📭 Bank is empty — will use a default question tomorrow.")
            return
        embed = discord.Embed(
            title="Next QOTD Preview",
            description=f"**{question_row['question']}**",
            color=config.COLOR_INFO,
        )
        embed.set_footer(text=f"ID: {question_row['id']} • Added by <@{question_row['added_by']}>")
        await ctx.send(embed=embed)

    @qotd_group.command(name="post")
    @commands.has_permissions(manage_guild=True)
    async def qotd_post(self, ctx: commands.Context) -> None:
        """Force-post a QOTD right now."""
        cfg = await db.get_qotd_config()
        channel_id = cfg.get("channel_id") if cfg else None
        if not channel_id:
            await ctx.send("❌ QOTD channel not set. Run `gl.qotd setchannel #channel` first.")
            return
        async with ctx.typing():
            ok = await self._post_qotd(channel_id, cfg.get("ping_role_id"))
        if ok:
            now = datetime.now(timezone.utc)
            await db.set_qotd_last_posted(now.strftime("%Y-%m-%d"))
            await ctx.send("✅ QOTD posted!")
        else:
            await ctx.send("❌ Failed to post QOTD. Check my permissions in that channel.")

    @qotd_group.command(name="setchannel")
    @commands.has_permissions(manage_guild=True)
    async def qotd_setchannel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the channel where QOTD posts."""
        await db.update_qotd_config({"channel_id": channel.id})
        await ctx.send(f"✅ QOTD channel set to {channel.mention}.")

    @qotd_group.command(name="setrole")
    @commands.has_permissions(manage_guild=True)
    async def qotd_setrole(self, ctx: commands.Context, role: discord.Role) -> None:
        """Set the role to ping when QOTD posts."""
        await db.update_qotd_config({"ping_role_id": role.id})
        await ctx.send(f"✅ QOTD ping role set to {role.mention}.")

    @qotd_group.command(name="settime")
    @commands.has_permissions(manage_guild=True)
    async def qotd_settime(self, ctx: commands.Context, time_str: str) -> None:
        """Set the daily post time in UTC 24h format, e.g. 09:00 or 18:30."""
        try:
            h, m = map(int, time_str.split(":"))
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except ValueError:
            await ctx.send("❌ Invalid time. Use HH:MM format, e.g. `09:00` or `18:30` (UTC).")
            return
        await db.update_qotd_config({"post_time": f"{h:02d}:{m:02d}"})
        await ctx.send(f"✅ QOTD will post daily at `{h:02d}:{m:02d}` UTC.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QOTD(bot))
