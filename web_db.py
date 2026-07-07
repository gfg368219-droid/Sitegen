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

def add_accounts(service_id: int, accounts: list[tuple], account_type: str = "email") -> int:
    """Insert accounts into stock. Returns number of rows actually inserted."""
    added = 0
    with _db() as cur:
        for identifier, password in accounts:
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
) -> dict:
    with _db() as cur:
        cur.execute(
            """INSERT INTO web_users (discord_id, username, avatar, access_token, refresh_token, last_seen)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON CONFLICT (discord_id) DO UPDATE SET
                   username = EXCLUDED.username,
                   avatar = EXCLUDED.avatar,
                   access_token = EXCLUDED.access_token,
                   refresh_token = EXCLUDED.refresh_token,
                   last_seen = NOW()
               RETURNING *""",
            (discord_id, username, avatar, access_token, refresh_token),
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
               ORDER BY gen_count DESC
               LIMIT %s""",
            (limit,),
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
