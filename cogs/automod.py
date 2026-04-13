"""
cogs/automod.py — AutoMod system. Listeners only, no commands.
"""
from __future__ import annotations
import logging, re, time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional
import discord
from discord.ext import commands
from config import GUILD_ID, SPAM_THRESHOLD, SPAM_WINDOW, DUPLICATE_THRESHOLD, DUPLICATE_WINDOW, CAPS_THRESHOLD, CAPS_MIN_LENGTH, MENTION_THRESHOLD, MAX_LINKS_PER_MESSAGE
from database import db
from utils import embeds
from utils.cache import automod_rules_cache

log = logging.getLogger(__name__)
_RE_LINK   = re.compile(r"https?://\S+", re.IGNORECASE)
_RE_INVITE = re.compile(r"(discord\.gg/|discord\.com/invite/)\S+", re.IGNORECASE)

class AutoModCog(commands.Cog, name="AutoMod"):
    def __init__(self, bot):
        self.bot = bot
        self._spam_buckets: dict[int, deque] = defaultdict(deque)
        self._dup_buckets:  dict[int, deque] = defaultdict(deque)
        self._bad_word_patterns: list[re.Pattern] = []

    async def _load_rules(self) -> dict:
        cached = automod_rules_cache.get("rules")
        if cached is not None: return cached
        rows  = await db.get_automod_rules(GUILD_ID)
        rules = {r["rule_type"]: {"enabled": r["enabled"], "config": r.get("config") or {}} for r in rows}
        bw    = rules.get("bad_words", {})
        if bw.get("enabled") and bw.get("config", {}).get("words"):
            patterns = []
            for word in bw["config"]["words"]:
                try: patterns.append(re.compile(rf"\b{word}\b", re.IGNORECASE))
                except re.error: pass
            self._bad_word_patterns = patterns
        else:
            self._bad_word_patterns = []
        automod_rules_cache.set("rules", rules, ttl=60)
        return rules

    async def _handle_violation(self, message, rule, action="WARN", reason="AutoMod violation",
                                  timeout_duration=None, apply_mute=False):
        try: await message.delete()
        except (discord.Forbidden, discord.NotFound): pass
        member = message.author
        if not isinstance(member, discord.Member): return
        guild = message.guild
        if guild is None: return
        await db.ensure_user(member.id, guild.id)
        await db.create_case(user_id=member.id, moderator_id=self.bot.user.id,
                              action=action, reason=reason, guild_id=guild.id)
        if apply_mute:
            try:
                config = await db.get_guild_config(guild.id)
                muted_role_id = config.get("muted_role_id") if config else None
                if muted_role_id:
                    muted_role = guild.get_role(muted_role_id)
                    if muted_role and muted_role not in member.roles:
                        await member.add_roles(muted_role, reason=f"[AutoMod] {reason}")
            except discord.Forbidden: pass
        if timeout_duration:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=timeout_duration)
                await member.timeout(until, reason=reason)
            except discord.Forbidden: pass
        log_embed = embeds.automod_action(user=member, rule=rule, action_taken=action,
                                           message_preview=message.content)
        try:
            config = await db.get_guild_config(guild.id)
            if config and config.get("log_channel_id"):
                ch = guild.get_channel(config["log_channel_id"])
                if ch and isinstance(ch, discord.TextChannel):
                    await ch.send(embed=log_embed)
        except Exception as exc: log.warning("automod log: %s", exc)
        try: await message.channel.send(f"⚠️ {member.mention}, your message was removed. **Reason:** {reason}", delete_after=5)
        except discord.Forbidden: pass

    def _is_spam(self, user_id):
        now = time.monotonic(); bucket = self._spam_buckets[user_id]
        while bucket and now - bucket[0] > SPAM_WINDOW: bucket.popleft()
        bucket.append(now)
        return len(bucket) >= SPAM_THRESHOLD

    def _is_duplicate(self, user_id, content):
        now = time.monotonic(); bucket = self._dup_buckets[user_id]
        while bucket and now - bucket[0][1] > DUPLICATE_WINDOW: bucket.popleft()
        same = sum(1 for text, _ in bucket if text == content)
        bucket.append((content, now))
        return same >= DUPLICATE_THRESHOLD - 1

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.guild.id != GUILD_ID: return
        if message.author.bot: return
        config = await db.get_guild_config(GUILD_ID)
        if not config or not config.get("automod_enabled", True): return
        rules   = await self._load_rules()
        content = message.content
        if rules.get("anti_invite", {}).get("enabled", True) and _RE_INVITE.search(content):
            await self._handle_violation(message, rule="Anti-Invite", action="WARN",
                reason="AutoMod: Discord invite links are not allowed."); return
        if rules.get("anti_link", {}).get("enabled", False):
            if len(_RE_LINK.findall(content)) > MAX_LINKS_PER_MESSAGE:
                await self._handle_violation(message, rule="Anti-Link", action="WARN",
                    reason="AutoMod: Too many links."); return
        mention_rule = rules.get("anti_mention", {})
        threshold    = mention_rule.get("config", {}).get("threshold", MENTION_THRESHOLD)
        if mention_rule.get("enabled", True) and len(message.mentions) >= threshold:
            await self._handle_violation(message, rule="Mention Spam", action="MUTE",
                reason=f"AutoMod: Too many mentions ({len(message.mentions)}).",
                apply_mute=True, timeout_duration=300); return
        caps_rule = rules.get("anti_caps", {})
        if caps_rule.get("enabled", True) and len(content) >= CAPS_MIN_LENGTH:
            letters = [c for c in content if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= CAPS_THRESHOLD:
                await self._handle_violation(message, rule="Anti-Caps", action="WARN",
                    reason="AutoMod: Excessive caps."); return
        bw_rule = rules.get("bad_words", {})
        if bw_rule.get("enabled", True) and self._bad_word_patterns:
            for pattern in self._bad_word_patterns:
                if pattern.search(content):
                    await self._handle_violation(message, rule="Bad Word Filter", action="WARN",
                        reason="AutoMod: Prohibited language."); return
        if rules.get("anti_duplicate", {}).get("enabled", True) and content.strip():
            if self._is_duplicate(message.author.id, content.strip().lower()):
                await self._handle_violation(message, rule="Anti-Duplicate", action="WARN",
                    reason="AutoMod: Duplicate messages."); return
        if rules.get("anti_spam", {}).get("enabled", True):
            if self._is_spam(message.author.id):
                await self._handle_violation(message, rule="Anti-Spam", action="TIMEOUT",
                    reason="AutoMod: Message spam.", timeout_duration=60); return

async def setup(bot):
    await bot.add_cog(AutoModCog(bot))
