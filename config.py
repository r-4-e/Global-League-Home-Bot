"""
config.py — Central configuration for Elura
All environment-driven constants live here.
"""

import os
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Alias so the rest of the codebase can import BOT_TOKEN
BOT_TOKEN: str = TOKEN or ""

# ── Permission Role IDs ───────────────────────────────────────────────────────
# Only users with this role may use /warn, /unwarn, /history
WARN_ROLE_ID: int = 1415025708698308638

# ── Embed Colours ─────────────────────────────────────────────────────────────
COLOR_SUCCESS = 0x2ECC71  # green
COLOR_ERROR = 0xE74C3C    # red
COLOR_WARNING = 0xF39C12  # orange
COLOR_INFO = 0x3498DB     # blue
COLOR_MOD = 0x9B59B6      # purple
COLOR_LOG = 0x2C3E50      # dark

# ── Automod Defaults ──────────────────────────────────────────────────────────
SPAM_THRESHOLD = 5      # messages within SPAM_WINDOW seconds
SPAM_WINDOW = 5          # seconds
DUPLICATE_THRESHOLD = 3  # same message in DUPLICATE_WINDOW seconds
DUPLICATE_WINDOW = 10
CAPS_THRESHOLD = 0.70    # 70% caps triggers filter
CAPS_MIN_LENGTH = 8      # minimum message length to check caps
MENTION_THRESHOLD = 5    # mentions per message
MAX_LINKS_PER_MESSAGE = 2

# ── Pagination ────────────────────────────────────────────────────────────────
HISTORY_PAGE_SIZE = 5

# ── Background Task Intervals ────────────────────────────────────────────────
PUNISHMENT_CHECK_INTERVAL = 30  # seconds

# ── Anti-Alt Verification ────────────────────────────────────────────────────
VERIFY_CHANNEL_ID: int = int(os.getenv("VERIFY_CHANNEL_ID", "0"))
VERIFIED_ROLE_ID: int = int(os.getenv("VERIFIED_ROLE_ID", "0"))

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")

# Render sets RENDER_EXTERNAL_URL automatically — falls back to it if you
# haven't set PUBLIC_BASE_URL yourself.
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
OAUTH_REDIRECT_URI: str = f"{PUBLIC_BASE_URL.rstrip('/')}/callback" if PUBLIC_BASE_URL else ""

# Long random secret — generate with: python -c "import secrets; print(secrets.token_hex(32))"
IP_SALT: str = os.getenv("IP_SALT", "")
MIN_ACCOUNT_AGE_DAYS: int = int(os.getenv("MIN_ACCOUNT_AGE_DAYS", "7"))
VERIFY_TOKEN_TTL_SECONDS: int = int(os.getenv("VERIFY_TOKEN_TTL_SECONDS", "600"))
VERIFY_LOG_WEBHOOK_URL = os.getenv("VERIFY_LOG_WEBHOOK_URL")  # optional but recommended

# Render's own proxy is the only path into your app, so this defaults to
# true there. Only keep it true if you're certain nothing else can reach
# this service directly — otherwise X-Forwarded-For is spoofable.
TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "true").lower() == "true"
