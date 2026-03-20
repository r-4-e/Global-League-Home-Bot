"""
database.py — Async Supabase wrapper for Elura.

All DB calls are async.  A single module-level `db` instance is
imported everywhere else so there is exactly one connection pool.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import acreate_client, AsyncClient

from config import SUPABASE_URL, SUPABASE_KEY, GUILD_ID

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL schema (run once in Supabase SQL editor)
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
-- Guilds / server config
CREATE TABLE IF NOT EXISTS guilds (
    guild_id          BIGINT PRIMARY KEY,
    log_channel_id    BIGINT,
    muted_role_id     BIGINT,
    automod_enabled   BOOLEAN DEFAULT TRUE,
    setup_complete    BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    guild_id   BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, guild_id)
);

-- Moderation cases
CREATE TABLE IF NOT EXISTS cases (
    case_id       BIGSERIAL PRIMARY KEY,
    guild_id      BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    moderator_id  BIGINT NOT NULL,
    action        TEXT NOT NULL,
    reason        TEXT,
    timestamp     TIMESTAMPTZ DEFAULT NOW(),
    active        BOOLEAN DEFAULT TRUE,
    expires_at    TIMESTAMPTZ,
    extra_data    JSONB
);

CREATE INDEX IF NOT EXISTS idx_cases_guild_user ON cases(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_cases_active     ON cases(active, expires_at) WHERE active = TRUE;

-- Staff notes
CREATE TABLE IF NOT EXISTS notes (
    note_id      BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    content      TEXT NOT NULL,
    timestamp    TIMESTAMPTZ DEFAULT NOW()
);

-- Permission overrides
CREATE TABLE IF NOT EXISTS permissions_override (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  BIGINT NOT NULL,
    role_id   BIGINT NOT NULL,
    command   TEXT NOT NULL,
    allowed   BOOLEAN DEFAULT TRUE,
    UNIQUE(guild_id, role_id, command)
);

-- Automod rules
CREATE TABLE IF NOT EXISTS auto_mod_rules (
    id         BIGSERIAL PRIMARY KEY,
    guild_id   BIGINT NOT NULL,
    rule_type  TEXT NOT NULL,
    enabled    BOOLEAN DEFAULT TRUE,
    config     JSONB,
    UNIQUE(guild_id, rule_type)
);

-- Help stats
CREATE TABLE IF NOT EXISTS help_stats (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  BIGINT NOT NULL,
    command   TEXT NOT NULL,
    uses      INT DEFAULT 1,
    last_used TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(guild_id, command)
);
"""


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class Database:
    """Thin async wrapper around supabase-py AsyncClient."""

    def __init__(self) -> None:
        self._client: Optional[AsyncClient] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._client = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase async client ready.")

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            raise RuntimeError("Database.connect() has not been called yet.")
        return self._client

    # ── Guild config ─────────────────────────────────────────────────────────

    async def get_guild_config(self, guild_id: int = GUILD_ID) -> Optional[dict]:
        try:
            res = (
                await self.client.table("guilds")
                .select("*")
                .eq("guild_id", guild_id)
                .maybe_single()
                .execute()
            )
            return res.data
        except Exception as exc:
            log.error("get_guild_config: %s", exc)
            return None

    async def upsert_guild_config(self, data: dict) -> bool:
        data.setdefault("guild_id", GUILD_ID)
        try:
            await (
                self.client.table("guilds")
                .upsert(data, on_conflict="guild_id")
                .execute()
            )
            return True
        except Exception as exc:
            log.error("upsert_guild_config: %s", exc)
            return False

    # ── Case management ──────────────────────────────────────────────────────

    async def create_case(
        self,
        user_id: int,
        moderator_id: int,
        action: str,
        reason: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        extra_data: Optional[dict] = None,
        guild_id: int = GUILD_ID,
    ) -> Optional[int]:
        """Insert a case and return its case_id."""
        payload: dict[str, Any] = {
            "guild_id":     guild_id,
            "user_id":      user_id,
            "moderator_id": moderator_id,
            "action":       action,
            "reason":       reason,
            "active":       True,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        if expires_at:
            payload["expires_at"] = expires_at.isoformat()
        if extra_data:
            payload["extra_data"] = extra_data
        try:
            res = await self.client.table("cases").insert(payload).execute()
            if res.data:
                return res.data[0]["case_id"]
        except Exception as exc:
            log.error("create_case: %s", exc)
        return None

    async def get_cases(
        self,
        user_id: int,
        guild_id: int = GUILD_ID,
        page: int = 1,
        page_size: int = 5,
    ) -> tuple[list[dict], int]:
        """Return (cases_page, total_count)."""
        try:
            offset = (page - 1) * page_size
            count_res = (
                await self.client.table("cases")
                .select("case_id", count="exact")
                .eq("guild_id", guild_id)
                .eq("user_id", user_id)
                .execute()
            )
            total = count_res.count or 0
            res = (
                await self.client.table("cases")
                .select("*")
                .eq("guild_id", guild_id)
                .eq("user_id", user_id)
                .order("timestamp", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            return res.data or [], total
        except Exception as exc:
            log.error("get_cases: %s", exc)
            return [], 0

    async def deactivate_case(self, case_id: int) -> bool:
        try:
            await (
                self.client.table("cases")
                .update({"active": False})
                .eq("case_id", case_id)
                .execute()
            )
            return True
        except Exception as exc:
            log.error("deactivate_case: %s", exc)
            return False

    async def get_active_timed_punishments(
        self, guild_id: int = GUILD_ID
    ) -> list[dict]:
        """Return cases that are active AND have a non-null expires_at in the past."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            res = (
                await self.client.table("cases")
                .select("*")
                .eq("guild_id", guild_id)
                .eq("active", True)
                .not_.is_("expires_at", "null")
                .lte("expires_at", now)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            log.error("get_active_timed_punishments: %s", exc)
            return []

    # ── Automod rules ────────────────────────────────────────────────────────

    async def get_automod_rules(self, guild_id: int = GUILD_ID) -> list[dict]:
        try:
            res = (
                await self.client.table("auto_mod_rules")
                .select("*")
                .eq("guild_id", guild_id)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            log.error("get_automod_rules: %s", exc)
            return []

    async def upsert_automod_rule(
        self,
        rule_type: str,
        enabled: bool,
        config: Optional[dict] = None,
        guild_id: int = GUILD_ID,
    ) -> bool:
        try:
            await (
                self.client.table("auto_mod_rules")
                .upsert(
                    {
                        "guild_id":  guild_id,
                        "rule_type": rule_type,
                        "enabled":   enabled,
                        "config":    config or {},
                    },
                    on_conflict="guild_id,rule_type",
                )
                .execute()
            )
            return True
        except Exception as exc:
            log.error("upsert_automod_rule: %s", exc)
            return False

    # ── Help stats ───────────────────────────────────────────────────────────

    async def increment_help_stat(
        self, command: str, guild_id: int = GUILD_ID
    ) -> None:
        try:
            existing = (
                await self.client.table("help_stats")
                .select("id, uses")
                .eq("guild_id", guild_id)
                .eq("command", command)
                .maybe_single()
                .execute()
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            if existing.data:
                await (
                    self.client.table("help_stats")
                    .update({"uses": existing.data["uses"] + 1, "last_used": now_iso})
                    .eq("id", existing.data["id"])
                    .execute()
                )
            else:
                await (
                    self.client.table("help_stats")
                    .insert(
                        {
                            "guild_id":  guild_id,
                            "command":   command,
                            "uses":      1,
                            "last_used": now_iso,
                        }
                    )
                    .execute()
                )
        except Exception as exc:
            log.error("increment_help_stat: %s", exc)

    # ── Notes ─────────────────────────────────────────────────────────────────

    async def add_note(
        self,
        user_id: int,
        moderator_id: int,
        content: str,
        guild_id: int = GUILD_ID,
    ) -> Optional[int]:
        """Insert a staff note and return its note_id."""
        try:
            res = await (
                self.client.table("notes")
                .insert(
                    {
                        "guild_id":     guild_id,
                        "user_id":      user_id,
                        "moderator_id": moderator_id,
                        "content":      content,
                        "timestamp":    datetime.now(timezone.utc).isoformat(),
                    }
                )
                .execute()
            )
            if res.data:
                return res.data[0]["note_id"]
        except Exception as exc:
            log.error("add_note: %s", exc)
        return None

    async def get_notes(
        self,
        user_id: int,
        guild_id: int = GUILD_ID,
    ) -> list[dict]:
        """Return all staff notes for a user."""
        try:
            res = (
                await self.client.table("notes")
                .select("*")
                .eq("guild_id", guild_id)
                .eq("user_id", user_id)
                .order("timestamp", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            log.error("get_notes: %s", exc)
            return []

    async def delete_note(self, note_id: int) -> bool:
        """Delete a staff note by ID."""
        try:
            await (
                self.client.table("notes")
                .delete()
                .eq("note_id", note_id)
                .execute()
            )
            return True
        except Exception as exc:
            log.error("delete_note: %s", exc)
            return False

    # ── Permissions override ──────────────────────────────────────────────────

    async def set_permission_override(
        self,
        role_id: int,
        command: str,
        allowed: bool,
        guild_id: int = GUILD_ID,
    ) -> bool:
        """Upsert a role-based command permission override."""
        try:
            await (
                self.client.table("permissions_override")
                .upsert(
                    {
                        "guild_id": guild_id,
                        "role_id":  role_id,
                        "command":  command,
                        "allowed":  allowed,
                    },
                    on_conflict="guild_id,role_id,command",
                )
                .execute()
            )
            return True
        except Exception as exc:
            log.error("set_permission_override: %s", exc)
            return False

    async def get_permission_overrides(
        self, guild_id: int = GUILD_ID
    ) -> list[dict]:
        """Return all permission overrides for a guild."""
        try:
            res = (
                await self.client.table("permissions_override")
                .select("*")
                .eq("guild_id", guild_id)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            log.error("get_permission_overrides: %s", exc)
            return []

    async def check_permission_override(
        self,
        role_ids: list[int],
        command: str,
        guild_id: int = GUILD_ID,
    ) -> Optional[bool]:
        """
        Check if any of the given role IDs have an override for `command`.
        Returns True/False if an override exists, None if no override found.
        Precedence: explicit ALLOW beats DENY when a user has multiple roles.
        """
        if not role_ids:
            return None
        try:
            res = (
                await self.client.table("permissions_override")
                .select("role_id, allowed")
                .eq("guild_id", guild_id)
                .eq("command", command)
                .in_("role_id", role_ids)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None
            # Allow wins if ANY matching role is allowed
            if any(r["allowed"] for r in rows):
                return True
            return False
        except Exception as exc:
            log.error("check_permission_override: %s", exc)
            return None

    # ── User ─────────────────────────────────────────────────────────────────

    async def ensure_user(self, user_id: int, guild_id: int = GUILD_ID) -> None:
        try:
            await (
                self.client.table("users")
                .upsert(
                    {"user_id": user_id, "guild_id": guild_id},
                    on_conflict="user_id,guild_id",
                )
                .execute()
            )
        except Exception as exc:
            log.error("ensure_user: %s", exc)


# Module-level singleton
db = Database()
