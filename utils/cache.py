"""
utils/cache.py — Simple async-safe in-memory cache with optional TTL.

Used to hold guild config, role IDs, and automod settings so the bot
doesn't round-trip to Supabase on every event.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional


class TTLCache:
    """
    Thread-safe (asyncio-safe) key/value store with per-entry TTL.

    Usage::

        cache = TTLCache(default_ttl=300)
        cache.set("guild_config", data)
        data = cache.get("guild_config")       # None after TTL expires
        cache.invalidate("guild_config")
    """

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


# ---------------------------------------------------------------------------
# Bot-wide caches
# ---------------------------------------------------------------------------

guild_config_cache = TTLCache(default_ttl=120)   # guild config (2 min)
automod_rules_cache = TTLCache(default_ttl=60)   # automod rules (1 min)
