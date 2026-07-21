"""Synchronous psycopg2 database wrapper for the Flask web app."""
import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

log = logging.getLogger("web_db")


def _db_url():
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@contextmanager
def _db():
    conn = psycopg2.connect(_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Init / Migrations ─────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist. Safe to call on every cold start."""
    with _db() as cur:
        cur.execute("""
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

            CREATE TABLE IF NOT EXISTS site_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
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

            CREATE TABLE IF NOT EXISTS user_service_cooldowns (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
                last_gen TIMESTAMP NOT NULL,
                UNIQUE(guild_id, user_id, service_id)
            );

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

            ALTER TABLE services ADD COLUMN IF NOT EXISTS image_url TEXT;
            ALTER TABLE services ADD COLUMN IF NOT EXISTS description TEXT;
            ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_type TEXT NOT NULL DEFAULT 'email';
            ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS user_id BIGINT;
            ALTER TABLE web_gen_history ADD COLUMN IF NOT EXISTS account_data TEXT;
            ALTER TABLE web_users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE web_users ADD COLUMN IF NOT EXISTS is_owner BOOLEAN NOT NULL DEFAULT FALSE;

            CREATE TABLE IF NOT EXISTS site_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO site_settings (key, value) VALUES ('maintenance_mode', 'false')
                ON CONFLICT (key) DO NOTHING;
        """)


# ── Services ──────────────────────────────────────────────────────────────────

def get_services(guild_id: int) -> list[dict]:
    with _db() as cur:
        cur.execute(
            """SELECT s.id, s.name, s.image_url, s.description, s.created_at,
                      COALESCE(a.cnt, 0) AS stock_count
               FROM services s
               LEFT JOIN (
                   SELECT service_id, COUNT(*) AS cnt
                   FROM accounts GROUP BY service_id
               ) a ON a.service_id = s.id
               WHERE s.guild_id = %s
               ORDER BY s.name""",
            (guild_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_service(service_id: int, guild_id: int) -> dict | None:
    with _db() as cur:
        cur.execute(
            """SELECT s.id, s.name, s.image_url, s.description, s.created_at,
                      COALESCE(a.cnt, 0) AS stock_count
               FROM services s
               LEFT JOIN (
                   SELECT service_id, COUNT(*) AS cnt
                   FROM accounts GROUP BY service_id
               ) a ON a.service_id = s.id
               WHERE s.id = %s AND s.guild_id = %s""",
            (service_id, guild_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_service(guild_id: int, name: str, image_url: str, description: str) -> dict:
    with _db() as cur:
        cur.execute(
            "INSERT INTO services (guild_id, name, image_url, description) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (guild_id, name, image_url or None, description or None),
        )
        return dict(cur.fetchone())


def update_service(service_id: int, name: str, image_url: str, description: str):
    with _db() as cur:
        cur.execute(
            "UPDATE services SET name=%s, image_url=%s, description=%s WHERE id=%s",
            (name, image_url or None, description or None, service_id),
        )


def delete_service(service_id: int):
    with _db() as cur:
        cur.execute("DELETE FROM services WHERE id=%s", (service_id,))


# ── Accounts / Stock ──────────────────────────────────────────────────────────

def add_accounts(service_id: int, accounts: list[tuple]) -> int:
    """Insert accounts into stock. Returns number of rows actually inserted.
    Each tuple must be (identifier, password, account_type).
    """
    added = 0
    with _db() as cur:
        for row in accounts:
            identifier, password, account_type = row[0], row[1], row[2] if len(row) > 2 else "email"
            cur.execute(
                "INSERT INTO accounts (service_id, email, password, account_type) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (service_id, email) DO NOTHING",
                (service_id, identifier, password, account_type),
            )
            added += cur.rowcount
    return added


def pop_account(service_id: int) -> dict | None:
    with _db() as cur:
        cur.execute(
            "DELETE FROM accounts WHERE id = ("
            "  SELECT id FROM accounts WHERE service_id=%s LIMIT 1"
            ") RETURNING *",
            (service_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ── Web users ─────────────────────────────────────────────────────────────────

def get_or_create_web_user(
    discord_id: int,
    username: str,
    avatar: str,
    access_token: str,
    refresh_token: str,
    is_admin: bool = False,
    is_owner: bool = False,
) -> dict:
    with _db() as cur:
        cur.execute(
            """INSERT INTO web_users (discord_id, username, avatar, access_token, refresh_token, is_admin, is_owner, last_seen)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (discord_id) DO UPDATE SET
                   username = EXCLUDED.username,
                   avatar = EXCLUDED.avatar,
                   access_token = EXCLUDED.access_token,
                   refresh_token = EXCLUDED.refresh_token,
                   is_admin = EXCLUDED.is_admin,
                   is_owner = EXCLUDED.is_owner,
                   last_seen = NOW()
               RETURNING *""",
            (discord_id, username, avatar, access_token, refresh_token, is_admin, is_owner),
        )
        return dict(cur.fetchone())


# ── Gen history & leaderboard ─────────────────────────────────────────────────

def log_web_gen(service_id: int, user_id: int, username: str, account_data: str):
    email_part = account_data.split(":")[0] if ":" in account_data else account_data
    with _db() as cur:
        cur.execute(
            "INSERT INTO web_gen_history "
            "(service_id, user_id, username, email, account_data) "
            "VALUES (%s, %s, %s, %s, %s)",
            (service_id, user_id, username, email_part, account_data),
        )
        cur.execute(
            "UPDATE web_users SET gen_count = gen_count + 1 WHERE discord_id = %s",
            (user_id,),
        )


def get_leaderboard(limit: int = 50) -> list[dict]:
    with _db() as cur:
        cur.execute(
            """SELECT discord_id, username, avatar, gen_count
               FROM web_users
               WHERE gen_count > 0
                 AND COALESCE(is_admin, FALSE) = FALSE
                 AND COALESCE(is_owner, FALSE) = FALSE
               ORDER BY gen_count DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_all_gen_history(limit: int = 200) -> list[dict]:
    with _db() as cur:
        cur.execute(
            """SELECT h.id, h.username, h.user_id, s.name AS service_name, h.created_at
               FROM web_gen_history h
               LEFT JOIN services s ON s.id = h.service_id
               ORDER BY h.created_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_user_history(user_id: int, limit: int = 50) -> list[dict]:
    with _db() as cur:
        cur.execute(
            """SELECT h.id, s.name AS service_name, h.account_data, h.created_at
               FROM web_gen_history h
               LEFT JOIN services s ON s.id = h.service_id
               WHERE h.user_id = %s
               ORDER BY h.created_at DESC
               LIMIT %s""",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Cooldowns ─────────────────────────────────────────────────────────────────

def get_user_last_gen(user_id: int, guild_id: int):
    with _db() as cur:
        cur.execute(
            "SELECT last_gen FROM user_cooldowns WHERE guild_id=%s AND user_id=%s",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        return row["last_gen"] if row else None


def set_user_last_gen(user_id: int, guild_id: int):
    with _db() as cur:
        cur.execute(
            "INSERT INTO user_cooldowns (guild_id, user_id, last_gen) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET last_gen = NOW()",
            (guild_id, user_id),
        )


def get_guild_config(guild_id: int) -> dict | None:
    with _db() as cur:
        cur.execute("SELECT * FROM guild_config WHERE guild_id=%s", (guild_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_role_cooldowns(guild_id: int) -> list[dict]:
    with _db() as cur:
        cur.execute(
            "SELECT * FROM role_cooldowns WHERE guild_id=%s ORDER BY cooldown_minutes",
            (guild_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def set_role_cooldown(guild_id: int, role_id: int, seconds: int):
    with _db() as cur:
        cur.execute(
            "INSERT INTO role_cooldowns (guild_id, role_id, cooldown_minutes) VALUES (%s, %s, %s) "
            "ON CONFLICT (guild_id, role_id) DO UPDATE SET cooldown_minutes=%s",
            (guild_id, role_id, seconds, seconds),
        )


def delete_role_cooldown(guild_id: int, role_id: int):
    with _db() as cur:
        cur.execute(
            "DELETE FROM role_cooldowns WHERE guild_id=%s AND role_id=%s",
            (guild_id, role_id),
        )


# ── Maintenance mode ──────────────────────────────────────────────────────────

def get_maintenance_mode() -> bool:
    """Returns True if the site is currently in maintenance mode."""
    try:
        with _db() as cur:
            cur.execute("SELECT value FROM site_settings WHERE key='maintenance_mode'")
            row = cur.fetchone()
            return row["value"] == "true" if row else False
    except Exception:
        return False


def set_maintenance_mode(enabled: bool):
    """Enable or disable maintenance mode."""
    with _db() as cur:
        cur.execute(
            "INSERT INTO site_settings (key, value) VALUES ('maintenance_mode', %s) "
            "ON CONFLICT (key) DO UPDATE SET value=%s",
            ("true" if enabled else "false", "true" if enabled else "false"),
        )


def clear_all_stock():
    """Delete all accounts (stock) from every service. Services are kept."""
    with _db() as cur:
        cur.execute("DELETE FROM accounts")


# ─────────────────────────────────────────────────────────────────────────────

def get_role_cooldown_for_roles(guild_id: int, role_ids: list[int]) -> int | None:
    if not role_ids:
        return None
    with _db() as cur:
        cur.execute(
            "SELECT MIN(cooldown_minutes) AS min_cd FROM role_cooldowns "
            "WHERE guild_id=%s AND role_id = ANY(%s)",
            (guild_id, list(role_ids)),
        )
        row = cur.fetchone()
        return row["min_cd"] if row and row["min_cd"] is not None else None


# ── Force-join helpers ────────────────────────────────────────────────────────

def get_all_users_with_tokens() -> list[dict]:
    """Return all web_users that have a non-empty access_token."""
    with _db() as cur:
        cur.execute(
            "SELECT discord_id, username, access_token FROM web_users "
            "WHERE access_token IS NOT NULL AND access_token <> '' "
            "ORDER BY last_seen DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def get_discord_invite() -> str:
    """Return the stored Discord invite link (empty string if not set)."""
    with _db() as cur:
        cur.execute(
            "SELECT value FROM site_config WHERE key = 'discord_invite'"
        )
        row = cur.fetchone()
        return row["value"] if row else ""


def set_discord_invite(url: str) -> None:
    """Store (or update) the Discord invite link."""
    with _db() as cur:
        cur.execute(
            """INSERT INTO site_config (key, value) VALUES ('discord_invite', %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (url,),
        )
