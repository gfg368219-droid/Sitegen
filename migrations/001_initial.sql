CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    emoji TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    password TEXT NOT NULL,
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
