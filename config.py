"""
config.py — Central configuration for Elura
All environment-driven constants live here.
"""

import os
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

TOKEN        = os.getenv("TOKEN")
GUILD_ID     = int(os.getenv("GUILD_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Alias so the rest of the codebase can import BOT_TOKEN
BOT_TOKEN: str = TOKEN or ""

# ── Permission Role IDs ───────────────────────────────────────────────────────
# Only users with this role may use /warn, /unwarn, /history
WARN_ROLE_ID: int = 1415025708698308638

# ── Embed Colours ─────────────────────────────────────────────────────────────
COLOR_SUCCESS = 0x2ECC71   # green
COLOR_ERROR   = 0xE74C3C   # red
COLOR_WARNING = 0xF39C12   # orange
COLOR_INFO    = 0x3498DB   # blue
COLOR_MOD     = 0x9B59B6   # purple
COLOR_LOG     = 0x2C3E50   # dark

# ── Automod Defaults ──────────────────────────────────────────────────────────
SPAM_THRESHOLD          = 5    # messages within SPAM_WINDOW seconds
SPAM_WINDOW             = 5    # seconds
DUPLICATE_THRESHOLD     = 3    # same message in DUPLICATE_WINDOW seconds
DUPLICATE_WINDOW        = 10
CAPS_THRESHOLD          = 0.70 # 70 % caps triggers filter
CAPS_MIN_LENGTH         = 8    # minimum message length to check caps
MENTION_THRESHOLD       = 5    # mentions per message
MAX_LINKS_PER_MESSAGE   = 2

# ── Pagination ────────────────────────────────────────────────────────────────
HISTORY_PAGE_SIZE = 5

# ── Background Task Intervals ────────────────────────────────────────────────
PUNISHMENT_CHECK_INTERVAL = 30  # seconds
