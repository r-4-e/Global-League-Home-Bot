-- ============================================================
-- Elura Bot — Supabase Schema
-- Run this once in your Supabase project SQL editor.
-- ============================================================

-- Guilds / server config
CREATE TABLE IF NOT EXISTS guilds (
    guild_id          BIGINT PRIMARY KEY,
    log_channel_id    BIGINT,
    muted_role_id     BIGINT,
    staff_role_id     BIGINT,
    automod_enabled   BOOLEAN DEFAULT TRUE,
    setup_complete    BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- If you already ran the schema and need to add the column:
-- ALTER TABLE guilds ADD COLUMN IF NOT EXISTS staff_role_id BIGINT;

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

-- Permission overrides (future extensibility)
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

-- ============================================================
-- Seed default automod rules for your guild
-- Replace 0 with your actual GUILD_ID
-- ============================================================

/*
INSERT INTO auto_mod_rules (guild_id, rule_type, enabled, config) VALUES
  (YOUR_GUILD_ID, 'anti_spam',      TRUE, '{"threshold": 5, "window": 5}'),
  (YOUR_GUILD_ID, 'anti_duplicate', TRUE, '{"threshold": 3, "window": 10}'),
  (YOUR_GUILD_ID, 'anti_link',      FALSE, '{}'),
  (YOUR_GUILD_ID, 'anti_invite',    TRUE, '{}'),
  (YOUR_GUILD_ID, 'anti_caps',      TRUE, '{"threshold": 0.70, "min_length": 8}'),
  (YOUR_GUILD_ID, 'anti_mention',   TRUE, '{"threshold": 5}'),
  (YOUR_GUILD_ID, 'bad_words',      FALSE, '{"words": ["badword1", "badword2"]}')
ON CONFLICT (guild_id, rule_type) DO NOTHING;
*/
