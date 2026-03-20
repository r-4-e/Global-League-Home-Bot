"""
cogs/automod.py — Automod event listener for Elura.

Detection rules:
  • Anti-spam         — burst of messages within SPAM_WINDOW seconds
  • Duplicate msgs    — same text sent repeatedly
  • Anti-link         — external HTTP/HTTPS links
  • Anti-invite       — discord.gg / discord.com/invite links
  • Anti-caps         — excessive uppercase
  • Mention spam      — too many @mentions in one message
  • Bad word filter   — regex-based word list from DB

Each violation: warn case created + message deleted + optional timeout.
All configurable per-guild via /setup or /automod_config (future).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional

import discord
from discord.ext import commands

from config import (
    GUILD_ID,
    SPAM_THRESHOLD,
    SPAM_WINDOW,
    DUPLICATE_THRESHOLD,
    DUPLICATE_WINDOW,
    CAPS_THRESHOLD,
    CAPS_MIN_LENGTH,
    MENTION_THRESHOLD,
    MAX_LINKS_PER_MESSAGE,
)
from database import db
from utils import embeds
from utils.cache import automod_rules_cache

log = logging.getLogger(__name__)

# ── Compiled patterns ──────────────────────────────────────────────────────
_RE_LINK    = re.compile(r"https?://\S+", re.IGNORECASE)
_RE_INVITE  = re.compile(r"(discord\.gg/|discord\.com/invite/)\S+", re.IGNORECASE)


class AutoModCog(commands.Cog, name="AutoMod"):
    """Real-time automod listener."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._guild = discord.Object(id=GUILD_ID)

        # In-memory rate-limit buckets
        # { user_id: deque of timestamps }
        self._spam_buckets: dict[int, deque] = defaultdict(deque)
        # { user_id: deque of (text, timestamp) }
        self._dup_buckets:  dict[int, deque] = defaultdict(deque)

        # Bad-word patterns loaded from DB — refreshed on first event
        self._bad_word_patterns: list[re.Pattern] = []
        self._rules_loaded = False

    # ── Rule loader ────────────────────────────────────────────────────────

    async def _load_rules(self) -> dict[str, dict]:
        """
        Return a dict of { rule_type: {enabled, config} }.
        Uses a short cache to avoid repeated DB round-trips.
        """
        cached = automod_rules_cache.get("rules")
        if cached is not None:
            return cached

        rows = await db.get_automod_rules(GUILD_ID)
        rules: dict[str, dict] = {}
        for row in rows:
            rules[row["rule_type"]] = {
                "enabled": row["enabled"],
                "config":  row.get("config") or {},
            }

        # Load bad-word patterns
        bw_rule = rules.get("bad_words", {})
        if bw_rule.get("enabled") and bw_rule.get("config", {}).get("words"):
            patterns = []
            for word in bw_rule["config"]["words"]:
                try:
                    patterns.append(re.compile(rf"\b{word}\b", re.IGNORECASE))
                except re.error:
                    pass
            self._bad_word_patterns = patterns
        else:
            self._bad_word_patterns = []

        automod_rules_cache.set("rules", rules, ttl=60)
        return rules

    # ── Core helper: handle violation ─────────────────────────────────────

    async def _handle_violation(
        self,
        message: discord.Message,
        rule: str,
        action: str = "WARN",
        reason: str = "AutoMod violation",
        timeout_duration: Optional[int] = None,  # seconds
        apply_mute: bool = False,
    ) -> None:
        """
        Delete the offending message, create a case, log it.
        action   — case action string stored in DB (WARN / MUTE / TIMEOUT)
        apply_mute   — also give the member the configured muted role
        timeout_duration — also Discord-timeout the member N seconds
        """
        # Delete message silently
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        member = message.author
        if not isinstance(member, discord.Member):
            return

        guild = message.guild
        if guild is None:
            return

        # Create case
        await db.ensure_user(member.id, guild.id)
        case_id = await db.create_case(
            user_id=member.id,
            moderator_id=self.bot.user.id,
            action=action,
            reason=reason,
            guild_id=guild.id,
        )

        # Apply muted role if requested
        if apply_mute:
            try:
                config = await db.get_guild_config(guild.id)
                muted_role_id = config.get("muted_role_id") if config else None
                if muted_role_id:
                    muted_role = guild.get_role(muted_role_id)
                    if muted_role and muted_role not in member.roles:
                        await member.add_roles(
                            muted_role, reason=f"[AutoMod] {reason}"
                        )
            except discord.Forbidden:
                pass
            except Exception as exc:
                log.warning("automod mute failed: %s", exc)

        # Apply Discord timeout if requested
        if timeout_duration:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=timeout_duration)
                await member.timeout(until, reason=reason)
            except discord.Forbidden:
                pass

        # Log to log channel
        log_embed = embeds.automod_action(
            user=member,
            rule=rule,
            action_taken=action,
            message_preview=message.content,
        )
        try:
            config = await db.get_guild_config(guild.id)
            if config and config.get("log_channel_id"):
                ch = guild.get_channel(config["log_channel_id"])
                if ch and isinstance(ch, discord.TextChannel):
                    await ch.send(embed=log_embed)
        except Exception as exc:
            log.warning("automod log failed: %s", exc)

        # Notify user in channel (deletes after 5s)
        try:
            notify = await message.channel.send(
                f"⚠️ {member.mention}, your message was removed. **Reason:** {reason}",
                delete_after=5,
            )
        except discord.Forbidden:
            pass

    # ── Spam detection ─────────────────────────────────────────────────────

    def _is_spam(self, user_id: int) -> bool:
        now = time.monotonic()
        bucket = self._spam_buckets[user_id]
        # Evict old entries
        while bucket and now - bucket[0] > SPAM_WINDOW:
            bucket.popleft()
        bucket.append(now)
        return len(bucket) >= SPAM_THRESHOLD

    # ── Duplicate detection ───────────────────────────────────────────────

    def _is_duplicate(self, user_id: int, content: str) -> bool:
        now = time.monotonic()
        bucket = self._dup_buckets[user_id]
        while bucket and now - bucket[0][1] > DUPLICATE_WINDOW:
            bucket.popleft()
        same = sum(1 for text, _ in bucket if text == content)
        bucket.append((content, now))
        return same >= DUPLICATE_THRESHOLD - 1

    # ── Main listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore DMs, bots, and other guilds
        if not message.guild or message.guild.id != GUILD_ID:
            return
        if message.author.bot:
            return

        # Check if automod is enabled globally
        config = await db.get_guild_config(GUILD_ID)
        if not config or not config.get("automod_enabled", True):
            return

        rules = await self._load_rules()
        content = message.content

        # ── Discord invite ────────────────────────────────────────────────
        invite_rule = rules.get("anti_invite", {})
        if invite_rule.get("enabled", True) and _RE_INVITE.search(content):
            await self._handle_violation(
                message,
                rule="Anti-Invite",
                action="WARN",
                reason="AutoMod: Discord invite links are not allowed.",
            )
            return

        # ── Anti-link ─────────────────────────────────────────────────────
        link_rule = rules.get("anti_link", {})
        if link_rule.get("enabled", False):
            links = _RE_LINK.findall(content)
            if len(links) > MAX_LINKS_PER_MESSAGE:
                await self._handle_violation(
                    message,
                    rule="Anti-Link",
                    action="WARN",
                    reason="AutoMod: Too many links in one message.",
                )
                return

        # ── Mention spam ──────────────────────────────────────────────────
        mention_rule = rules.get("anti_mention", {})
        threshold = mention_rule.get("config", {}).get("threshold", MENTION_THRESHOLD)
        if mention_rule.get("enabled", True) and len(message.mentions) >= threshold:
            await self._handle_violation(
                message,
                rule="Mention Spam",
                action="MUTE",
                reason=f"AutoMod: Too many mentions ({len(message.mentions)}).",
                apply_mute=True,
                timeout_duration=300,  # 5 min timeout as backup
            )
            return

        # ── Anti-caps ─────────────────────────────────────────────────────
        caps_rule = rules.get("anti_caps", {})
        if caps_rule.get("enabled", True) and len(content) >= CAPS_MIN_LENGTH:
            letters = [c for c in content if c.isalpha()]
            if letters:
                ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if ratio >= CAPS_THRESHOLD:
                    await self._handle_violation(
                        message,
                        rule="Anti-Caps",
                        action="WARN",
                        reason="AutoMod: Excessive caps detected.",
                    )
                    return

        # ── Bad words ─────────────────────────────────────────────────────
        bw_rule = rules.get("bad_words", {})
        if bw_rule.get("enabled", True) and self._bad_word_patterns:
            for pattern in self._bad_word_patterns:
                if pattern.search(content):
                    await self._handle_violation(
                        message,
                        rule="Bad Word Filter",
                        action="WARN",
                        reason="AutoMod: Prohibited language detected.",
                    )
                    return

        # ── Duplicate messages ────────────────────────────────────────────
        dup_rule = rules.get("anti_duplicate", {})
        if dup_rule.get("enabled", True) and content.strip():
            if self._is_duplicate(message.author.id, content.strip().lower()):
                await self._handle_violation(
                    message,
                    rule="Anti-Duplicate",
                    action="WARN",
                    reason="AutoMod: Duplicate messages detected.",
                )
                return

        # ── Spam ──────────────────────────────────────────────────────────
        spam_rule = rules.get("anti_spam", {})
        if spam_rule.get("enabled", True):
            if self._is_spam(message.author.id):
                await self._handle_violation(
                    message,
                    rule="Anti-Spam",
                    action="TIMEOUT",
                    reason="AutoMod: Message spam detected.",
                    timeout_duration=60,  # 1 min timeout
                )
                return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoModCog(bot))
