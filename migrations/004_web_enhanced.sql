-- Add image + description to services
ALTER TABLE services ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE services ADD COLUMN IF NOT EXISTS description TEXT;

-- Add account type to accounts (email or user)
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_type TEXT NOT NULL DEFAULT 'email';

-- Web users for OAuth sessions
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

-- Extend web_gen_history with user_id and full credential
ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS account_data TEXT;
