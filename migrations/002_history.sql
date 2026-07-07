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
    created_at TIMESTAMP DEFAULT NOW()
);
