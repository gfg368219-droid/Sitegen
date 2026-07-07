import discord
from discord.ext import commands, tasks
import database
from datetime import datetime, timezone


def service_label(service) -> str:
    if service["emoji"]:
        return f"{service['emoji']} {service['name']}"
    return service["name"]


async def build_gen_embed(guild: discord.Guild) -> discord.Embed:
    services = await database.get_services(guild.id)
    config = await database.get_config(guild.id)

    embed = discord.Embed(
        title="Generation de comptes",
        color=0x2B2D31
    )

    if not services:
        embed.description = "Aucun service disponible pour le moment."
    else:
        lines = []
        for s in services:
            count = await database.count_accounts(s["id"])
            label = service_label(s)
            lines.append(f"{label} : {count}")
        embed.description = "\n".join(lines)

    if config and config["default_cooldown"]:
        embed.add_field(
            name="Cooldown",
            value=f"{config['default_cooldown']} min",
            inline=True
        )

    return embed


async def build_gen_view(guild: discord.Guild, bot) -> discord.ui.View:
    services = await database.get_services(guild.id)
    view = GenView(bot)
    for i, s in enumerate(services[:25]):
        count = await database.count_accounts(s["id"])
        label = service_label(s)[:80]
        btn = GenButton(
            service_id=s["id"],
            label=label,
            available=count > 0
        )
        btn.row = i // 5
        view.add_item(btn)
    return view


class GenButton(discord.ui.Button):
    def __init__(self, service_id: int, label: str, available: bool):
        style = discord.ButtonStyle.secondary if available else discord.ButtonStyle.danger
        super().__init__(
            label=label,
            style=style,
            custom_id=f"gen:{service_id}",
            disabled=not available
        )
        self.service_id = service_id

    async def callback(self, interaction: discord.Interaction):
        config = await database.get_config(interaction.guild_id)

        if config and config["required_role_id"]:
            role_ids = {r.id for r in interaction.user.roles}
            if config["required_role_id"] not in role_ids:
                role = interaction.guild.get_role(config["required_role_id"])
                name = role.name if role else str(config["required_role_id"])
                await interaction.response.send_message(
                    f"Vous avez besoin du role **{name}** pour generer un compte.",
                    ephemeral=True
                )
                return

        user_role_ids = [r.id for r in interaction.user.roles]
        role_cooldown_seconds = await database.get_role_cooldown_for_roles(
            interaction.guild_id, user_role_ids
        )

        if role_cooldown_seconds is not None:
            cooldown_seconds = role_cooldown_seconds
        else:
            default_minutes = config["default_cooldown"] if config else 60
            cooldown_seconds = default_minutes * 60

        last_gen = await database.get_user_last_gen(interaction.guild_id, interaction.user.id)
        if last_gen:
            if last_gen.tzinfo is None:
                last_gen = last_gen.replace(tzinfo=timezone.utc)
            elapsed_seconds = (datetime.now(timezone.utc) - last_gen).total_seconds()
            remaining_seconds = cooldown_seconds - elapsed_seconds
            if remaining_seconds > 0:
                mins = int(remaining_seconds // 60)
                secs = int(remaining_seconds % 60)
                if mins > 0:
                    temps = f"**{mins}m {secs}s**"
                else:
                    temps = f"**{secs}s**"
                await interaction.response.send_message(
                    f"Vous devez attendre encore {temps} avant de generer un autre compte.",
                    ephemeral=True
                )
                return

        account = await database.pop_account(self.service_id)
        if not account:
            await interaction.response.send_message(
                "Ce service est vide. Revenez plus tard.",
                ephemeral=True
            )
            gen_cog = self.view.bot.cogs.get("Gen") if self.view else None
            if gen_cog:
                await gen_cog.refresh_embed(interaction.guild)
            return

        await database.set_user_last_gen(interaction.guild_id, interaction.user.id)

        service = await database.get_service_by_id(self.service_id)
        label = service_label(service) if service else "Service"

        embed = discord.Embed(
            title=f"Compte {label}",
            color=discord.Color.green()
        )
        embed.add_field(name="Email", value=f"||{account['email']}||", inline=False)
        embed.add_field(name="Mot de passe", value=f"||{account['password']}||", inline=False)
        if cooldown_seconds >= 60:
            cd_mins = int(cooldown_seconds // 60)
            cd_secs = int(cooldown_seconds % 60)
            cd_display = f"{cd_mins}m {cd_secs}s" if cd_secs else f"{cd_mins}m"
        else:
            cd_display = f"{int(cooldown_seconds)}s"
        embed.set_footer(text=f"Ne partagez pas ce compte. Prochain gen dans {cd_display}.")

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message(
                "Votre compte a ete envoye en message prive.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(embed=embed, ephemeral=True)

        gen_cog = self.view.bot.cogs.get("Gen") if self.view else None
        if gen_cog:
            await gen_cog.refresh_embed(interaction.guild)


class GenView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot


class Gen(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._gen_messages: dict[int, discord.Message] = {}
        self.refresh_task.start()

    def cog_unload(self):
        self.refresh_task.cancel()

    async def refresh_embed(self, guild: discord.Guild):
        config = await database.get_config(guild.id)
        if not config or not config["gen_channel_id"]:
            return

        channel = guild.get_channel(config["gen_channel_id"])
        if not channel:
            return

        embed = await build_gen_embed(guild)
        view = await build_gen_view(guild, self.bot)

        existing_msg: discord.Message = self._gen_messages.get(guild.id)

        if existing_msg is None and config["gen_message_id"]:
            try:
                existing_msg = await channel.fetch_message(config["gen_message_id"])
                self._gen_messages[guild.id] = existing_msg
            except (discord.NotFound, discord.HTTPException):
                existing_msg = None

        if existing_msg:
            try:
                await existing_msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                existing_msg = None
                self._gen_messages.pop(guild.id, None)

        msg = await channel.send(embed=embed, view=view)
        self._gen_messages[guild.id] = msg
        await database.update_config(guild.id, gen_message_id=msg.id)

    @tasks.loop(seconds=30)
    async def refresh_task(self):
        for guild in self.bot.guilds:
            try:
                await self.refresh_embed(guild)
            except Exception:
                pass

    @refresh_task.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Gen(bot))
