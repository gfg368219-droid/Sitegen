import asyncpg
import logging
import os
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("database")

pool: asyncpg.Pool = None


def _fix_db_url(url: str) -> str:
    """Railway fournit postgres:// mais asyncpg requiert postgresql://"""
    if url and url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


async def create_pool():
    global pool
    raw_url = os.getenv("NEON_DB_URL") or os.getenv("DATABASE_URL", "")
    url = _fix_db_url(raw_url)
    if not url:
        raise RuntimeError("Aucune URL de base de donnees trouvee (NEON_DB_URL ou DATABASE_URL)")
    log.info("Connexion via : %s", "NEON_DB_URL" if os.getenv("NEON_DB_URL") else "DATABASE_URL")
    pool = await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=10,
        command_timeout=30
    )
    log.info("Pool asyncpg cree (min=2, max=10, timeout=30s)")
    return pool


async def run_migrations() -> list[str]:
    applied = []
    migration_dir = "migrations"
    files = sorted(f for f in os.listdir(migration_dir) if f.endswith(".sql"))

    if not files:
        log.warning("Aucun fichier SQL trouve dans %s/", migration_dir)
        return applied

    async with pool.acquire() as conn:
        for fname in files:
            path = f"{migration_dir}/{fname}"
            log.info("Application de la migration : %s", fname)
            try:
                with open(path) as f:
                    sql = f.read()
                await conn.execute(sql)
                applied.append(fname)
                log.info("Migration reussie : %s", fname)
            except Exception as e:
                log.error("Echec de la migration %s : %s", fname, e)
                raise

    log.info("%d migration(s) appliquee(s) au total", len(applied))
    return applied


# ── Services ──────────────────────────────────────────────────────────────────

async def get_services(guild_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM services WHERE guild_id = $1 ORDER BY name",
            guild_id
        )


async def get_service_by_id(service_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM services WHERE id = $1",
            service_id
        )


async def create_service(guild_id: int, name: str, emoji: str = None):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO services (guild_id, name, emoji) VALUES ($1, $2, $3) RETURNING *",
            guild_id, name, emoji
        )
    log.info("[SERVICE] Cree : '%s' (guild=%s, emoji=%s)", name, guild_id, emoji)
    return row


async def delete_service(service_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM services WHERE id = $1 RETURNING name, guild_id",
            service_id
        )
    if row:
        log.info("[SERVICE] Supprime : '%s' (guild=%s)", row["name"], row["guild_id"])


# ── Accounts ──────────────────────────────────────────────────────────────────

async def add_accounts(service_id: int, accounts: list[tuple[str, str]]):
    async with pool.acquire() as conn:
        result = await conn.executemany(
            "INSERT INTO accounts (service_id, email, password) VALUES ($1, $2, $3) "
            "ON CONFLICT (service_id, email) DO NOTHING",
            [(service_id, email, pwd) for email, pwd in accounts]
        )
    log.info("[ACCOUNTS] %d compte(s) ajoutes au service %s (doublons ignores)",
             len(accounts), service_id)
    return result


async def count_accounts(service_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM accounts WHERE service_id = $1",
            service_id
        )


async def pop_account(service_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM accounts WHERE id = ("
            "  SELECT id FROM accounts WHERE service_id = $1 LIMIT 1"
            ") RETURNING *",
            service_id
        )
    if row:
        log.info("[GEN] Compte distribue depuis service %s -> %s", service_id, row["email"])
    else:
        log.warning("[GEN] Aucun compte disponible pour le service %s", service_id)
    return row


# ── Guild config ───────────────────────────────────────────────────────────────

async def get_config(guild_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM guild_config WHERE guild_id = $1",
            guild_id
        )
        if not row:
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id
            )
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )
            log.info("[CONFIG] Nouvelle config creee pour guild %s", guild_id)
        return row


async def update_config(guild_id: int, **kwargs):
    if not kwargs:
        return
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    set_clause = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO guild_config (guild_id) VALUES ($1) "
            f"ON CONFLICT (guild_id) DO UPDATE SET {set_clause}",
            guild_id, *vals
        )
    log.info("[CONFIG] Mise a jour guild %s : %s", guild_id,
             ", ".join(f"{k}={v}" for k, v in kwargs.items()))


# ── Role cooldowns ─────────────────────────────────────────────────────────────

async def set_role_cooldown(guild_id: int, role_id: int, minutes: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO role_cooldowns (guild_id, role_id, cooldown_minutes) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (guild_id, role_id) DO UPDATE SET cooldown_minutes = $3",
            guild_id, role_id, minutes
        )
    log.info("[COOLDOWN] Role %s sur guild %s -> %d min", role_id, guild_id, minutes)


async def delete_role_cooldown(guild_id: int, role_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM role_cooldowns WHERE guild_id = $1 AND role_id = $2",
            guild_id, role_id
        )
    log.info("[COOLDOWN] Supprime pour role %s sur guild %s", role_id, guild_id)


async def get_role_cooldowns(guild_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM role_cooldowns WHERE guild_id = $1",
            guild_id
        )


async def get_role_cooldown_for_roles(guild_id: int, role_ids: list[int]):
    if not role_ids:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT MIN(cooldown_minutes) FROM role_cooldowns "
            "WHERE guild_id = $1 AND role_id = ANY($2)",
            guild_id, role_ids
        )


# ── User cooldowns ─────────────────────────────────────────────────────────────

async def get_user_last_gen(guild_id: int, user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT last_gen FROM user_cooldowns WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id
        )


async def set_user_last_gen(guild_id: int, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_cooldowns (guild_id, user_id, last_gen) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET last_gen = NOW()",
            guild_id, user_id
        )
    log.debug("[COOLDOWN] Cooldown enregistre pour user %s sur guild %s", user_id, guild_id)


# ── Restock history ────────────────────────────────────────────────────────────

async def log_restock_history(
    service_id: int,
    guild_id: int,
    added_by: str,
    account_count: int,
    accounts: list[tuple[str, str]],
    source: str = "discord"
):
    async with pool.acquire() as conn:
        history_id = await conn.fetchval(
            "INSERT INTO restock_history (service_id, guild_id, added_by, account_count, source) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            service_id, guild_id, added_by, account_count, source
        )
        await conn.executemany(
            "INSERT INTO restock_history_accounts (history_id, email, password) VALUES ($1, $2, $3)",
            [(history_id, email, pwd) for email, pwd in accounts]
        )
    log.info("[RESTOCK] Historique #%d enregistre : %d comptes par '%s' (source=%s, guild=%s)",
             history_id, account_count, added_by, source, guild_id)
    return history_id
