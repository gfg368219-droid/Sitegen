"""Run all database migrations against DATABASE_URL.

Usage:
    DATABASE_URL=postgres://... python migrate.py
"""
import os
import sys
import psycopg2

SQL = """
-- 001_initial
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    emoji TEXT,
    image_url TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    password TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'email',
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(service_id, email)
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id BIGINT PRIMARY KEY,
    notif_channel_id BIGINT,
    gen_channel_id BIGINT,
    gen_message_id BIGINT,
    required_role_id BIGINT,
    default_cooldown INTEGER DEFAULT 60
);

CREATE TABLE IF NOT EXISTS role_cooldowns (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    cooldown_minutes INTEGER NOT NULL,
    UNIQUE(guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_cooldowns (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    last_gen TIMESTAMP NOT NULL,
    UNIQUE(guild_id, user_id)
);

-- 002_history
CREATE TABLE IF NOT EXISTS restock_history (
    id SERIAL PRIMARY KEY,
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    guild_id BIGINT,
    added_by TEXT NOT NULL,
    account_count INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'discord',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS restock_history_accounts (
    id SERIAL PRIMARY KEY,
    history_id INTEGER NOT NULL REFERENCES restock_history(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_gen_history (
    id SERIAL PRIMARY KEY,
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    account_data TEXT,
    user_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 003_service_cooldown
CREATE TABLE IF NOT EXISTS user_service_cooldowns (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    last_gen TIMESTAMP NOT NULL,
    UNIQUE(guild_id, user_id, service_id)
);

-- 004_web_enhanced
CREATE TABLE IF NOT EXISTS web_users (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '',
    access_token TEXT NOT NULL DEFAULT '',
    refresh_token TEXT NOT NULL DEFAULT '',
    gen_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Alter existing tables (idempotent)
ALTER TABLE services ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE services ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_type TEXT NOT NULL DEFAULT 'email';
ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS account_data TEXT;
"""


def main():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    print("Connecting to database...")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()
        print("All migrations applied successfully.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
