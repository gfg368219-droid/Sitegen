import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import database
from datetime import datetime, timezone


async def _send_restock_webhook(service_name: str, image_url: str | None, added: int) -> None:
    """POST a Discord embed to DISCORD_WEBHOOK. Never raises."""
    url = os.getenv("DISCORD_WEBHOOK")
    if not url:
        return
    plural = "s" if added > 1 else ""
    embed = {
        "title": f"Restock +{added} compte{plural} {service_name}",
        "color": 0x7C3AED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "ProaltsGen"},
    }
    if image_url:
        embed["thumbnail"] = {"url": image_url}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass

RESTOCK_ROLE_ID = 1517909085453029487


def _parse_accounts(text: str) -> list[tuple[str, str, str]]:
    """Parse accounts from .txt content.
    Returns list of (identifier, password, account_type).
    - Discards everything after | on each line
    - Skips http/https lines
    - Skips lines without identifier:password
    - account_type = "email" if @ in identifier, else "user"
    """
    accounts = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            line = line.split("|", 1)[0].strip()
        if not line or "http" in line.lower():
            continue
        if ":" not in line:
            continue
        idx = line.index(":")
        identifier = line[:idx].strip()
        password = line[idx + 1:].strip()
        if not identifier or not password:
            continue
        if "/" in identifier or "\\" in identifier or " " in identifier:
            continue
        account_type = "email" if "@" in identifier else "user"
        accounts.append((identifier, password, account_type))
    return accounts


def service_label(service) -> str:
    if service["emoji"]:
        return f"{service['emoji']} {service['name']}"
    return service["name"]


async def service_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    services = await database.get_services(interaction.guild_id)
    choices = []
    for s in services:
        label = service_label(s)
        if current.lower() in label.lower() or current.lower() in s["name"].lower():
            choices.append(app_commands.Choice(name=label[:100], value=str(s["id"])))
    return choices[:25]


class Restock(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="restock",
        description="Ajouter des comptes a un service depuis un fichier .txt"
    )
    @app_commands.describe(
        service="Nom du service a restock (liste des services disponibles)",
        fichier="Fichier .txt avec les comptes (format: email:motdepasse, un par ligne)"
    )
    @app_commands.autocomplete(service=service_autocomplete)
    async def restock(
        self,
        interaction: discord.Interaction,
        service: str,
        fichier: discord.Attachment
    ):
        role_ids = {r.id for r in interaction.user.roles}
        if RESTOCK_ROLE_ID not in role_ids:
            await interaction.response.send_message(
                "Vous n'avez pas la permission d'utiliser cette commande.",
                ephemeral=True
            )
            return

        if not fichier.filename.lower().endswith(".txt"):
            await interaction.response.send_message(
                "Le fichier doit etre au format `.txt`.",
                ephemeral=True
            )
            return

        try:
            service_id = int(service)
        except ValueError:
            await interaction.response.send_message(
                "Service invalide. Choisissez un service dans la liste proposee.",
                ephemeral=True
            )
            return

        svc = await database.get_service_by_id(service_id)
        if not svc or svc["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                "Service introuvable. Utilisez `/create` pour en creer un.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            raw = await fichier.read()
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            await interaction.followup.send("Impossible de lire le fichier.", ephemeral=True)
            return

        accounts = _parse_accounts(text)

        if not accounts:
            await interaction.followup.send(
                "Aucun compte valide trouve (format attendu: `identifiant:motdepasse` par ligne).",
                ephemeral=True
            )
            return

        await database.add_accounts(service_id, accounts)
        image_url = svc.get("image_url") if svc else None
        await _send_restock_webhook(svc["name"], image_url, len(accounts))
        new_count = await database.count_accounts(service_id)
        label = service_label(svc)

        await database.log_restock_history(
            service_id=service_id,
            guild_id=interaction.guild_id,
            added_by=str(interaction.user),
            account_count=len(accounts),
            accounts=[(r[0], r[1]) for r in accounts],
            source="discord"
        )

        success_embed = discord.Embed(
            title="Restock effectue",
            color=discord.Color.green()
        )
        success_embed.add_field(name="Service", value=label, inline=True)
        success_embed.add_field(name="Ajoutes", value=str(len(accounts)), inline=True)
        success_embed.add_field(name="Total en stock", value=str(new_count), inline=True)
        success_embed.set_footer(
            text=f"Restock le {datetime.now(timezone.utc).strftime('%d/%m/%Y a %H:%M')} UTC"
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

        config = await database.get_config(interaction.guild_id)
        if config and config["notif_channel_id"]:
            channel = interaction.guild.get_channel(config["notif_channel_id"])
            if channel:
                notif_embed = discord.Embed(
                    title="Restock",
                    description=f"**{new_count}** compte(s) **{label}** disponibles",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                notif_embed.set_footer(text=f"Restock par {interaction.user.display_name}")
                await channel.send(
                    "@here",
                    embed=notif_embed,
                    allowed_mentions=discord.AllowedMentions(everyone=True)
                )

        gen_cog = self.bot.cogs.get("Gen")
        if gen_cog:
            await gen_cog.refresh_embed(interaction.guild)

    @app_commands.command(
        name="erestock",
        description="Ajouter des comptes sans traitement du separateur | (garde tout le mot de passe)"
    )
    @app_commands.describe(
        service="Nom du service a restock (liste des services disponibles)",
        fichier="Fichier .txt avec les comptes (format: email:motdepasse, un par ligne)"
    )
    @app_commands.autocomplete(service=service_autocomplete)
    async def erestock(
        self,
        interaction: discord.Interaction,
        service: str,
        fichier: discord.Attachment
    ):
        role_ids = {r.id for r in interaction.user.roles}
        if RESTOCK_ROLE_ID not in role_ids:
            await interaction.response.send_message(
                "Vous n'avez pas la permission d'utiliser cette commande.",
                ephemeral=True
            )
            return

        if not fichier.filename.lower().endswith(".txt"):
            await interaction.response.send_message(
                "Le fichier doit etre au format `.txt`.",
                ephemeral=True
            )
            return

        try:
            service_id = int(service)
        except ValueError:
            await interaction.response.send_message(
                "Service invalide. Choisissez un service dans la liste proposee.",
                ephemeral=True
            )
            return

        svc = await database.get_service_by_id(service_id)
        if not svc or svc["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                "Service introuvable. Utilisez `/create` pour en creer un.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            raw = await fichier.read()
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            await interaction.followup.send("Impossible de lire le fichier.", ephemeral=True)
            return

        accounts = _parse_accounts(text)

        if not accounts:
            await interaction.followup.send(
                "Aucun compte valide trouve (format attendu: `identifiant:motdepasse` par ligne).",
                ephemeral=True
            )
            return

        await database.add_accounts(service_id, accounts)
        image_url = svc.get("image_url") if svc else None
        await _send_restock_webhook(svc["name"], image_url, len(accounts))
        new_count = await database.count_accounts(service_id)
        label = service_label(svc)

        await database.log_restock_history(
            service_id=service_id,
            guild_id=interaction.guild_id,
            added_by=str(interaction.user),
            account_count=len(accounts),
            accounts=[(r[0], r[1]) for r in accounts],
            source="discord"
        )

        success_embed = discord.Embed(
            title="Restock effectue",
            color=discord.Color.green()
        )
        success_embed.add_field(name="Service", value=label, inline=True)
        success_embed.add_field(name="Ajoutes", value=str(len(accounts)), inline=True)
        success_embed.add_field(name="Total en stock", value=str(new_count), inline=True)
        success_embed.set_footer(
            text=f"Restock le {datetime.now(timezone.utc).strftime('%d/%m/%Y a %H:%M')} UTC"
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

        config = await database.get_config(interaction.guild_id)
        if config and config["notif_channel_id"]:
            channel = interaction.guild.get_channel(config["notif_channel_id"])
            if channel:
                notif_embed = discord.Embed(
                    title="Restock",
                    description=f"**{new_count}** compte(s) **{label}** disponibles",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                notif_embed.set_footer(text=f"Restock par {interaction.user.display_name}")
                await channel.send(
                    "@here",
                    embed=notif_embed,
                    allowed_mentions=discord.AllowedMentions(everyone=True)
                )

        gen_cog = self.bot.cogs.get("Gen")
        if gen_cog:
            await gen_cog.refresh_embed(interaction.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Restock(bot))
