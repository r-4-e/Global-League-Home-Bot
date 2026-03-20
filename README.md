# Elura — Production Discord Moderation Bot

A production-grade, single-guild Discord moderation bot built with **Python 3.11+**, **discord.py 2.x**, and **Supabase (PostgreSQL)**.

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Setup](#setup)
5. [Commands Reference](#commands-reference)
6. [Permission System](#permission-system)
7. [AutoMod Rules](#automod-rules)
8. [Database Schema](#database-schema)
9. [Configuration](#configuration)

---

## Features

| System | Details |
|---|---|
| **Moderation** | 20 slash commands — warn, mute, timeout, kick, ban, mass actions, channel controls |
| **Permission Middleware** | Per-command Discord permission checks + role hierarchy enforcement |
| **AutoMod** | 7 configurable rules with auto-punishment and case creation |
| **Logging** | Structured embeds for all server events sent to log channel |
| **Setup Wizard** | Interactive UI with dropdowns/buttons to configure the bot |
| **Help Panel** | Category dropdown, paginated embeds, command examples |
| **Background Tasks** | Restart-safe expired punishment checker (every 30s) |
| **Supabase DB** | Persistent cases, configs, automod rules, help stats |
| **Cache Layer** | TTL cache for guild config and automod rules |

---

## Architecture

```
main.py            ← Bot class, setup_hook, global error handler
config.py          ← All environment constants
database.py        ← Async Supabase wrapper (singleton `db`)
utils/
  permissions.py   ← Permission middleware (every command routes here)
  embeds.py        ← Centralised embed factory
  cache.py         ← TTL in-memory cache
cogs/
  moderation.py    ← All 20 moderation slash commands
  automod.py       ← Message event listener + rule engine
  logging_cog.py   ← Server event forwarder
  setup_cog.py     ← /setup wizard + /config view
  help_cog.py      ← /help panel with dropdown + pagination
tasks/
  background.py    ← asyncio.create_task() background workers
schema.sql         ← Supabase schema (run once)
```

**Key design decisions:**
- **Single guild** — all app_commands use `guild=discord.Object(id=GUILD_ID)` for instant sync
- **No `bot.loop`** — tasks use `asyncio.create_task()` inside `setup_hook()`
- **Permission-first** — every command calls permission gate functions before acting
- **No silent failures** — every error produces a user-facing ephemeral message

---

## Project Structure

```
elura/
├── main.py
├── config.py
├── database.py
├── schema.sql
├── requirements.txt
├── .env.example
├── utils/
│   ├── __init__.py
│   ├── permissions.py
│   ├── embeds.py
│   └── cache.py
├── cogs/
│   ├── __init__.py
│   ├── moderation.py
│   ├── automod.py
│   ├── logging_cog.py
│   ├── setup_cog.py
│   └── help_cog.py
└── tasks/
    ├── __init__.py
    └── background.py
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A Discord bot application with the following enabled:
  - **Server Members Intent**
  - **Message Content Intent**
  - **Presence Intent** (optional)
- A [Supabase](https://supabase.com) project

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_server_id
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
```

### 4. Create the database schema

Open your Supabase project → SQL Editor → paste the contents of `schema.sql` and run.

Optionally uncomment and run the INSERT block at the bottom to seed default automod rules (replace `YOUR_GUILD_ID`).

### 5. Invite the bot

Required OAuth2 scopes: `bot`, `applications.commands`

Required bot permissions:
- Ban Members
- Kick Members
- Moderate Members
- Manage Roles
- Manage Messages
- Manage Channels
- Manage Nicknames
- View Audit Log

### 6. Run

```bash
python main.py
```

### 7. Configure in Discord

Run `/setup` in your server (requires Administrator) to:
- Select the log channel
- Select or skip the muted role
- Toggle automod on/off

---

## Commands Reference

### Moderation (requires Warn Role)
| Command | Description |
|---|---|
| `/warn <user> [reason]` | Issue a warning |
| `/unwarn <case_id>` | Remove a warning by case ID |
| `/history <user> [page]` | View paginated moderation history |

### Moderation (Discord permissions)
| Command | Permission Required |
|---|---|
| `/mute <user> [reason] [duration]` | Manage Roles |
| `/unmute <user> [reason]` | Manage Roles |
| `/timeout <user> [duration] [reason]` | Moderate Members |
| `/untimeout <user> [reason]` | Moderate Members |
| `/kick <user> [reason]` | Kick Members |
| `/ban <user> [reason] [delete_days]` | Ban Members |
| `/unban <user_id> [reason]` | Ban Members |
| `/softban <user> [reason]` | Ban Members |
| `/massban <ids> [reason]` | Ban Members |
| `/masskick <ids> [reason]` | Kick Members |
| `/clear <amount> [user]` | Manage Messages |
| `/slowmode <seconds> [channel]` | Manage Channels |
| `/lock [channel] [reason]` | Manage Channels |
| `/unlock [channel] [reason]` | Manage Channels |
| `/nick <user> [nickname]` | Manage Nicknames |
| `/role_add <user> <role>` | Manage Roles |
| `/role_remove <user> <role>` | Manage Roles |

### Configuration (Administrator)
| Command | Description |
|---|---|
| `/setup` | Launch the interactive setup wizard |
| `/config` | View current saved configuration |

### Info
| Command | Description |
|---|---|
| `/help` | Open the interactive help panel |

---

## Permission System

### Warn System (Special Case)

Only users with **Role ID `1415025708698308638`** may use:
- `/warn`, `/unwarn`, `/history`

All other users receive:
> ❌ You are not allowed to use warning commands.

### Standard Commands

Each command checks the relevant Discord permission. If missing:
> ❌ You need **"Ban Members"** permission to use this command.

The bot also checks its own permissions before acting:
> ❌ I don't have permission to perform this action.

### Role Hierarchy

- Cannot act on yourself
- Cannot act on the guild owner
- Cannot act on a member with an equal or higher top role
- Guild owner can always act on anyone

---

## AutoMod Rules

| Rule | Default | Description |
|---|---|---|
| `anti_spam` | ✅ ON | Detects 5+ messages in 5 seconds |
| `anti_duplicate` | ✅ ON | Detects 3+ identical messages in 10 seconds |
| `anti_link` | ❌ OFF | Removes HTTP/HTTPS links (configurable) |
| `anti_invite` | ✅ ON | Removes Discord invite links |
| `anti_caps` | ✅ ON | Removes messages >70% uppercase |
| `anti_mention` | ✅ ON | Warns when ≥5 mentions in one message |
| `bad_words` | ❌ OFF | Regex-based word filter (configure in DB) |

Rules are stored in the `auto_mod_rules` table and cached for 60 seconds. Toggle globally via `/setup` or adjust per-rule in the database.

To add bad words, update the `auto_mod_rules` row for `bad_words`:
```json
{"words": ["pattern1", "pattern2", "exact phrase"]}
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `guilds` | Per-guild configuration (log channel, muted role, automod toggle) |
| `users` | User registry (ensures FK integrity) |
| `cases` | Full moderation history with case IDs, actions, expiry |
| `notes` | Staff notes on users |
| `permissions_override` | Future role-based command overrides |
| `auto_mod_rules` | Per-rule automod configuration |
| `help_stats` | /help usage tracking |

---

## Configuration

All constants are in `config.py` (sourced from `.env`):

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `GUILD_ID` | The single guild this bot operates in |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon or service role key |
| `WARN_ROLE_ID` | Role ID required for warn commands |
| `SPAM_THRESHOLD` | Messages before spam trigger (default: 5) |
| `SPAM_WINDOW` | Spam detection window in seconds (default: 5) |
| `PUNISHMENT_CHECK_INTERVAL` | Expired punishment check frequency (default: 30s) |

---

## Production Notes

- **Restart-safe:** All timed punishments are stored in Supabase with `expires_at`. On restart, the background checker picks up where it left off within 30 seconds.
- **Zero blocking code:** All operations are async. No `time.sleep()`, no synchronous HTTP calls.
- **Cache invalidation:** Guild config cache is invalidated on `/setup` save. Automod rules cache TTL is 60 seconds.
- **Error resilience:** Every DB call, Discord API call, and background task is wrapped in try/except with structured logging.
