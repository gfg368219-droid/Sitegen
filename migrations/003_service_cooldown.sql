CREATE TABLE IF NOT EXISTS user_service_cooldowns (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    last_gen TIMESTAMP NOT NULL,
    UNIQUE(guild_id, user_id, service_id)
);
