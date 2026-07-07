import discord
from discord import app_commands
from discord.ext import commands
import database

RESTOCK_ROLE_ID = 1517909085453029487
CONFIG_ROLE_ID = 1517892778938470531


def has_admin(member: discord.Member) -> bool:
    ids = {r.id for r in member.roles}
    return RESTOCK_ROLE_ID in ids or CONFIG_ROLE_ID in ids


def service_label(service) -> str:
    if service["emoji"]:
        return f"{service['emoji']} {service['name']}"
    return service["name"]


class DeleteView(discord.ui.View):
    def __init__(self, services, bot):
        super().__init__(timeout=60)
        self.bot = bot
        options = []
        for s in services:
            options.append(
                discord.SelectOption(
                    label=service_label(s)[:100],
                    value=str(s["id"]),
                    description=f"ID {s['id']}"
                )
            )
        select = discord.ui.Select(
            placeholder="Choisir un service a supprimer...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)
        self.selected_service = None

    async def select_callback(self, interaction: discord.Interaction):
        service_id = int(interaction.data["values"][0])
        service = await database.get_service_by_id(service_id)
        if not service:
            await interaction.response.send_message("Service introuvable.", ephemeral=True)
            return

        await database.delete_service(service_id)
        label = service_label(service)

        embed = discord.Embed(
            title="Service supprime",
            description=f"Le service **{label}** et tous ses comptes ont ete supprimes.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

        gen_cog = self.bot.cogs.get("Gen")
        if gen_cog:
            await gen_cog.refresh_embed(interaction.guild)


class Services(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="create", description="Creer un nouveau service de generation")
    @app_commands.describe(
        name="Nom du service",
        emoji="Emoji du service (facultatif)"
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        emoji: str = None
    ):
        if not has_admin(interaction.user):
            await interaction.response.send_message(
                "Vous n'avez pas la permission d'utiliser cette commande.",
                ephemeral=True
            )
            return

        try:
            await database.create_service(interaction.guild_id, name, emoji)
        except Exception:
            await interaction.response.send_message(
                f"Un service nomme **{name}** existe deja dans ce serveur.",
                ephemeral=True
            )
            return

        label = f"{emoji} {name}" if emoji else name
        embed = discord.Embed(
            title="Service cree",
            description=f"Le service **{label}** a ete cree avec succes.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        gen_cog = self.bot.cogs.get("Gen")
        if gen_cog:
            await gen_cog.refresh_embed(interaction.guild)

    @app_commands.command(name="delete", description="Supprimer un service existant")
    async def delete(self, interaction: discord.Interaction):
        if not has_admin(interaction.user):
            await interaction.response.send_message(
                "Vous n'avez pas la permission d'utiliser cette commande.",
                ephemeral=True
            )
            return

        services = await database.get_services(interaction.guild_id)
        if not services:
            await interaction.response.send_message(
                "Aucun service n'existe encore. Utilisez /create pour en creer un.",
                ephemeral=True
            )
            return

        view = DeleteView(services, self.bot)
        embed = discord.Embed(
            title="Supprimer un service",
            description="Selectionnez le service a supprimer ci-dessous.\n"
                        "Tous les comptes associes seront egalement supprimes.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Services(bot))
