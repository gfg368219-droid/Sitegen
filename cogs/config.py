import discord
from discord import app_commands
from discord.ext import commands
import database

CONFIG_ROLE_ID = 1517892778938470531


class DefaultCooldownModal(discord.ui.Modal, title="Cooldown par defaut"):
    cooldown = discord.ui.TextInput(
        label="Cooldown en minutes",
        placeholder="Ex: 60",
        min_length=1,
        max_length=6
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = int(self.cooldown.value.strip())
            if minutes < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Valeur invalide. Entrez un nombre entier positif en minutes.",
                ephemeral=True
            )
            return
        await database.update_config(self.guild_id, default_cooldown=minutes)
        await interaction.response.send_message(
            f"Cooldown par defaut mis a jour: **{minutes} minute(s)**.",
            ephemeral=True
        )


class RoleCooldownModal(discord.ui.Modal, title="Cooldown par role"):
    cooldown = discord.ui.TextInput(
        label="Cooldown en secondes",
        placeholder="Ex: 30",
        min_length=1,
        max_length=6
    )

    def __init__(self, guild_id: int, role: discord.Role):
        super().__init__()
        self.guild_id = guild_id
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        try:
            seconds = int(self.cooldown.value.strip())
            if seconds < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Valeur invalide. Entrez un nombre entier positif en secondes.",
                ephemeral=True
            )
            return
        await database.set_role_cooldown(self.guild_id, self.role.id, seconds)
        await interaction.response.send_message(
            f"Cooldown du role **{self.role.name}** mis a jour: **{seconds} seconde(s)**.",
            ephemeral=True
        )


class RoleCooldownSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

        role_select = discord.ui.RoleSelect(
            placeholder="Rechercher un role...",
            min_values=1,
            max_values=1
        )
        role_select.callback = self.role_callback
        self.add_item(role_select)

    async def role_callback(self, interaction: discord.Interaction):
        role_id = int(interaction.data["values"][0])
        guild_role = interaction.guild.get_role(role_id)
        if not guild_role:
            await interaction.response.send_message("Role introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(
            RoleCooldownModal(interaction.guild_id, guild_role)
        )


class DeleteRoleCooldownView(discord.ui.View):
    def __init__(self, guild: discord.Guild, cooldowns):
        super().__init__(timeout=60)
        self.guild = guild
        options = []
        for rc in cooldowns:
            role = guild.get_role(rc["role_id"])
            name = role.name if role else f"Role {rc['role_id']}"
            options.append(
                discord.SelectOption(
                    label=f"{name} — {rc['cooldown_minutes']} s",
                    value=str(rc["role_id"])
                )
            )
        select = discord.ui.Select(
            placeholder="Choisir le role a retirer...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        role_id = int(interaction.data["values"][0])
        await database.delete_role_cooldown(interaction.guild_id, role_id)
        role = interaction.guild.get_role(role_id)
        name = role.name if role else str(role_id)
        await interaction.response.edit_message(
            content=f"Cooldown du role **{name}** supprime.",
            embed=None,
            view=None
        )


class ConfigMainView(discord.ui.View):
    def __init__(self, guild: discord.Guild, bot):
        super().__init__(timeout=120)
        self.guild = guild
        self.bot = bot

        options = [
            discord.SelectOption(
                label="Salon de notification restock",
                value="notif",
                description="Choisir le salon pour les annonces de restock",
                emoji="\U0001f514"
            ),
            discord.SelectOption(
                label="Salon de generation",
                value="gen",
                description="Choisir le salon ou les boutons de gen apparaissent",
                emoji="\U0001f3ae"
            ),
            discord.SelectOption(
                label="Role requis pour gen",
                value="req_role",
                description="Role minimum pour pouvoir gen un compte",
                emoji="\U0001f511"
            ),
            discord.SelectOption(
                label="Cooldown par defaut",
                value="cooldown",
                description="Temps entre deux gens pour un utilisateur (en minutes)",
                emoji="\U000023f1"
            ),
            discord.SelectOption(
                label="Cooldown par role",
                value="role_cooldown",
                description="Definir un cooldown specifique pour un role (en secondes)",
                emoji="\U0001f4cb"
            ),
            discord.SelectOption(
                label="Voir la configuration actuelle",
                value="view",
                description="Afficher tous les parametres configures",
                emoji="\U0001f4dd"
            ),
            discord.SelectOption(
                label="Supprimer un cooldown de role",
                value="del_role_cd",
                description="Retirer le cooldown specifique d'un role",
                emoji="\U0001f5d1"
            ),
        ]
        select = discord.ui.Select(
            placeholder="Choisir un parametre a configurer...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]

        if choice == "notif":
            view = discord.ui.View(timeout=60)
            cs = discord.ui.ChannelSelect(
                placeholder="Choisir le salon de notification...",
                channel_types=[discord.ChannelType.text]
            )
            async def notif_cb(inter):
                ch = cs.values[0]
                await database.update_config(inter.guild_id, notif_channel_id=ch.id)
                await inter.response.edit_message(
                    content=f"Salon de notification defini sur {ch.mention}.",
                    embed=None, view=None
                )
            cs.callback = notif_cb
            view.add_item(cs)
            await interaction.response.send_message(
                "Selectionnez le salon de notification:", view=view, ephemeral=True
            )

        elif choice == "gen":
            view = discord.ui.View(timeout=60)
            cs = discord.ui.ChannelSelect(
                placeholder="Choisir le salon de generation...",
                channel_types=[discord.ChannelType.text]
            )
            async def gen_cb(inter):
                ch = cs.values[0]
                await database.update_config(
                    inter.guild_id,
                    gen_channel_id=ch.id,
                    gen_message_id=None
                )
                await inter.response.edit_message(
                    content=f"Salon de generation defini sur {ch.mention}. "
                            "L'embed sera envoye au prochain rafraichissement.",
                    embed=None, view=None
                )
                gen_cog = self.bot.cogs.get("Gen")
                if gen_cog:
                    await gen_cog.refresh_embed(inter.guild)
            cs.callback = gen_cb
            view.add_item(cs)
            await interaction.response.send_message(
                "Selectionnez le salon de generation:", view=view, ephemeral=True
            )

        elif choice == "req_role":
            view = discord.ui.View(timeout=60)
            rs = discord.ui.RoleSelect(placeholder="Choisir le role requis pour gen...")
            async def role_cb(inter):
                role = rs.values[0]
                await database.update_config(inter.guild_id, required_role_id=role.id)
                await inter.response.edit_message(
                    content=f"Role requis pour gen defini sur **{role.name}**.",
                    embed=None, view=None
                )
            rs.callback = role_cb
            view.add_item(rs)
            await interaction.response.send_message(
                "Selectionnez le role requis pour utiliser les boutons de gen:",
                view=view, ephemeral=True
            )

        elif choice == "cooldown":
            await interaction.response.send_modal(
                DefaultCooldownModal(interaction.guild_id)
            )

        elif choice == "role_cooldown":
            view = RoleCooldownSelectView()
            await interaction.response.send_message(
                "Selectionnez le role pour lequel definir un cooldown:",
                view=view, ephemeral=True
            )

        elif choice == "del_role_cd":
            cooldowns = await database.get_role_cooldowns(interaction.guild_id)
            if not cooldowns:
                await interaction.response.send_message(
                    "Aucun cooldown de role configure.", ephemeral=True
                )
                return
            view = DeleteRoleCooldownView(interaction.guild, cooldowns)
            await interaction.response.send_message(
                "Choisir le role dont supprimer le cooldown:", view=view, ephemeral=True
            )

        elif choice == "view":
            config = await database.get_config(interaction.guild_id)
            cooldowns = await database.get_role_cooldowns(interaction.guild_id)

            notif_ch = interaction.guild.get_channel(config["notif_channel_id"]) if config["notif_channel_id"] else None
            gen_ch = interaction.guild.get_channel(config["gen_channel_id"]) if config["gen_channel_id"] else None
            req_role = interaction.guild.get_role(config["required_role_id"]) if config["required_role_id"] else None

            embed = discord.Embed(title="Configuration actuelle", color=discord.Color.blurple())
            embed.add_field(
                name="Salon notification",
                value=notif_ch.mention if notif_ch else "Non configure",
                inline=True
            )
            embed.add_field(
                name="Salon generation",
                value=gen_ch.mention if gen_ch else "Non configure",
                inline=True
            )
            embed.add_field(
                name="Role requis pour gen",
                value=req_role.mention if req_role else "Aucun (tous peuvent gen)",
                inline=True
            )
            embed.add_field(
                name="Cooldown par defaut",
                value=f"{config['default_cooldown']} minute(s)",
                inline=True
            )

            if cooldowns:
                lines = []
                for rc in cooldowns:
                    role = interaction.guild.get_role(rc["role_id"])
                    name = role.name if role else str(rc["role_id"])
                    lines.append(f"**{name}**: {rc['cooldown_minutes']} s")
                embed.add_field(
                    name="Cooldowns par role",
                    value="\n".join(lines),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Cooldowns par role",
                    value="Aucun configure",
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="config", description="Configurer le bot de generation")
    async def config(self, interaction: discord.Interaction):
        role_ids = {r.id for r in interaction.user.roles}
        if CONFIG_ROLE_ID not in role_ids:
            await interaction.response.send_message(
                "Vous n'avez pas la permission d'utiliser cette commande.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Configuration du bot",
            description="Selectionnez un parametre a modifier dans le menu ci-dessous.",
            color=discord.Color.blurple()
        )
        view = ConfigMainView(interaction.guild, self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
