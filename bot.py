import discord
from discord.ext import commands
import os
import logging
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv
import database

load_dotenv()

# ── Logger setup ──────────────────────────────────────────────────────────────

LOG_FMT = "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FMT,
    datefmt=DATE_FMT,
    handlers=[logging.StreamHandler()]
)

# Silence noisy discord internals (keep WARNING+)
for lib in ("discord.http", "discord.gateway", "discord.client", "discord.ext.commands.bot"):
    logging.getLogger(lib).setLevel(logging.WARNING)

log = logging.getLogger("bot")

COGS = [
    "cogs.services",
    "cogs.restock",
    "cogs.config",
    "cogs.gen",
]


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        log.info("=" * 60)
        log.info("Demarrage du bot Gen")
        log.info("=" * 60)

        # ── Base de donnees ───────────────────────────────────────────
        db_url = os.getenv("DATABASE_URL", "")
        masked = db_url.split("@")[-1] if "@" in db_url else "(non definie)"
        log.info("[DB] Connexion a PostgreSQL -> %s", masked)
        try:
            await database.create_pool()
            log.info("[DB] Pool de connexions cree avec succes")
        except Exception as e:
            log.critical("[DB] ECHEC connexion PostgreSQL : %s", e)
            log.debug(traceback.format_exc())
            raise

        # ── Migrations ────────────────────────────────────────────────
        log.info("[DB] Application des migrations SQL...")
        try:
            applied = await database.run_migrations()
            if applied:
                for fname in applied:
                    log.info("[DB] Migration appliquee : %s", fname)
            else:
                log.info("[DB] Aucune nouvelle migration a appliquer")
        except Exception as e:
            log.error("[DB] ECHEC migration : %s", e)
            log.debug(traceback.format_exc())
            raise

        # ── Chargement des cogs ───────────────────────────────────────
        log.info("[COGS] Chargement des extensions...")
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("[COGS] OK  %s", cog)
            except Exception as e:
                log.error("[COGS] ECHEC  %s : %s", cog, e)
                log.debug(traceback.format_exc())

        # ── Sync commandes slash ──────────────────────────────────────
        log.info("[SLASH] Synchronisation des commandes slash (global)...")
        try:
            synced = await self.tree.sync()
            log.info("[SLASH] %d commande(s) globale(s) : %s",
                     len(synced), ", ".join(f"/{c.name}" for c in synced))
        except Exception as e:
            log.error("[SLASH] ECHEC sync global : %s", e)
            log.debug(traceback.format_exc())

    async def on_ready(self):
        log.info("=" * 60)
        log.info("[BOT]  Connecte en tant que : %s", self.user)
        log.info("[BOT]  ID du bot            : %s", self.user.id)
        log.info("[BOT]  Serveurs rejoints     : %d", len(self.guilds))
        for guild in self.guilds:
            log.info("[BOT]    -> %s (ID: %s, membres: %s)",
                     guild.name, guild.id, guild.member_count)
            # Sync par guilde pour effet immediat (evite le delai global de 1h)
            try:
                self.tree.copy_global_to(guild=guild)
                guild_synced = await self.tree.sync(guild=guild)
                log.info("[SLASH] Sync guilde '%s' -> %d commande(s)", guild.name, len(guild_synced))
            except Exception as e:
                log.warning("[SLASH] Echec sync guilde '%s' : %s", guild.name, e)
        log.info("[BOT]  Latence gateway       : %.1f ms", self.latency * 1000)
        log.info("=" * 60)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="les comptes | /gen"
            )
        )
        log.info("[BOT]  Statut mis a jour")

    async def on_guild_join(self, guild: discord.Guild):
        log.info("[GUILD] Bot ajoute au serveur : %s (ID: %s)", guild.name, guild.id)

    async def on_guild_remove(self, guild: discord.Guild):
        log.warning("[GUILD] Bot retire du serveur : %s (ID: %s)", guild.name, guild.id)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError
    ):
        cmd = interaction.command.name if interaction.command else "inconnu"
        user = f"{interaction.user} (ID: {interaction.user.id})"
        log.error("[CMD] Erreur dans /%s utilise par %s : %s", cmd, user, error)
        log.error("[CMD] Traceback complet :\n%s", traceback.format_exc())
        msg = "Une erreur est survenue. Veuillez reessayer."
        if "pool" in str(error).lower() or "database" in str(error).lower():
            msg = "Erreur de base de donnees. Verifiez la variable DATABASE_URL."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ── Point d'entree ────────────────────────────────────────────────────────────

def main():
    log.info("[INIT] Verification des variables d'environnement...")

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.critical("[INIT] DISCORD_TOKEN manquant ! Ajoutez-le dans les secrets Replit.")
        raise SystemExit(1)

    masked_token = token[:10] + "..." + token[-5:]
    log.info("[INIT] DISCORD_TOKEN     : %s (masque)", masked_token)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.critical("[INIT] DATABASE_URL manquante ! Base de donnees non configuree.")
        raise SystemExit(1)
    log.info("[INIT] DATABASE_URL      : definie")
    log.info("[INIT] Demarrage du bot...")

    bot = Bot()
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        log.critical("[INIT] Token Discord invalide ! Verifiez DISCORD_TOKEN dans les secrets.")
        raise SystemExit(1)
    except Exception as e:
        log.critical("[INIT] Erreur fatale au demarrage : %s", e)
        log.debug(traceback.format_exc())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
