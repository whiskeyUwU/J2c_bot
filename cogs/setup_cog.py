
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
from utils.database import db, GuildConfig

class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup",
        description="[Admin] Set up the Join-to-Create VC system, category, and panel automatically.",
    )
    @app_commands.describe(
        category="(Optional) An existing category to put the JTC VC and panel in. Leave empty to create a new 'TempVC' category.",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        me = guild.me
        top_perms = guild.me.guild_permissions
        missing: list[str] = []
        if not top_perms.manage_channels:  missing.append("`Manage Channels`")
        if not top_perms.move_members:     missing.append("`Move Members`")
        if not top_perms.mute_members:     missing.append("`Mute Members`")
        if not top_perms.view_audit_log:   missing.append("`View Audit Log`")
        if not top_perms.send_messages:    missing.append("`Send Messages`")

        if missing:
            await interaction.followup.send(
                f"❌ The bot is missing the following server permissions needed for TempVC:\n"
                + "\n".join(f"  • {p}" for p in missing)
                + "\n\nPlease fix the bot's permissions and run `/setup` again.",
                ephemeral=True,
            )
            return

        existing_config = db.get_config(guild.id)
        if existing_config:

            if existing_config.shared_panel_message_id:
                old_panel_ch = guild.get_channel(existing_config.panel_channel_id)
                if old_panel_ch:
                    try:
                        old_msg = await old_panel_ch.fetch_message(existing_config.shared_panel_message_id)
                        await old_msg.delete()
                    except discord.HTTPException:
                        pass

        if category is None:
            category = discord.utils.get(guild.categories, name="TempVC")
            if category is None:
                category = await guild.create_category("TempVC", reason="TempVC: Setup")

        jtc_channel = await guild.create_voice_channel(
            name="➕ Join to Create",
            category=category,
            reason="TempVC: Setup — Join-to-Create channel",
        )

        panel_channel = await guild.create_text_channel(
            name="panel",
            category=category,
            topic="🎙️ TempVC Control Panel — Join the voice channel above to get your own!",
            reason="TempVC: Setup — panel channel",
        )

        log_channel = await guild.create_text_channel(
            name="tempvc-logs",
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
            },
            reason="TempVC: Setup — admin log channel",
        )

        config = GuildConfig(
            jtc_channel_id=jtc_channel.id,
            category_id=category.id,
            panel_channel_id=panel_channel.id,
            log_channel_id=log_channel.id,
        )
        db.set_config(guild.id, config)
        db.save()

        from cogs.panel_cog import TempVCSharedView, build_shared_embed
        shared_embed = build_shared_embed(guild)
        shared_view  = TempVCSharedView()
        shared_view.customize_for_guild(guild)
        file = discord.File("interface.png", filename="interface.png")
        shared_msg = await panel_channel.send(file=file, embed=shared_embed, view=shared_view)

        config.shared_panel_message_id = shared_msg.id
        db.save()

        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            guild,
            "⚙️ TempVC System Configured",
            f"TempVC system has been successfully set up by {interaction.user.mention}.",
            color=0x57F287,
            fields=[
                {"name": "Join-to-Create VC", "value": jtc_channel.mention, "inline": True},
                {"name": "Panel Channel", "value": panel_channel.mention, "inline": True},
                {"name": "Log Channel", "value": log_channel.mention, "inline": True},
            ]
        )

        embed = discord.Embed(
            title="✅ TempVC System Ready!",
            description=(
                f"Everything has been set up automatically.\n"
                f"Users can join {jtc_channel.mention} to get their own voice channel.\n"
                f"The shared control panel is live in {panel_channel.mention}.\n"
                f"Admin action logs will be sent to {log_channel.mention}."
            ),
            color=0x57F287,
        )
        embed.add_field(name="➕ Join-to-Create VC",  value=jtc_channel.mention,  inline=True)
        embed.add_field(name="📋 Panel Channel",       value=panel_channel.mention, inline=True)
        embed.add_field(name="📁 Category",            value=category.mention,      inline=True)
        embed.add_field(name="📜 Log Channel",         value=log_channel.mention,   inline=True)
        embed.set_footer(text="made with ❤️ by whiskey")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="tempvc-status",
        description="[Admin] Show all active temporary VCs in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    async def tempvc_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        active = [
            (ch_id, ch)
            for ch_id, ch in db._channels.items()
            if ch.guild_id == interaction.guild_id
        ]

        if not active:
            return await interaction.followup.send(
                "ℹ️ No active temporary VCs in this server.", ephemeral=True
            )

        lines: list[str] = []
        for ch_id, ch in active:
            vc = interaction.guild.get_channel(ch_id)
            owner = interaction.guild.get_member(ch.owner_id)
            vc_name   = vc.name    if vc    else f"(deleted #{ch_id})"
            owner_tag = owner.mention if owner else f"<@{ch.owner_id}>"
            lines.append(f"• **{vc_name}** — owned by {owner_tag}")

        embed = discord.Embed(
            title=f"🎙️ Active Temp VCs ({len(active)})",
            description="\n".join(lines),
            color=0x5865F2,
        )
        embed.set_footer(text="made with ❤️ by whiskey")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="tempvc-remove-penalty",
        description="[Admin] Restore a penalized VC owner's mute/move controls.",
    )
    @app_commands.describe(member="The VC owner whose penalty to remove")
    @app_commands.default_permissions(manage_guild=True)
    async def tempvc_remove_penalty(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        config = db.get_config(interaction.guild_id)
        if not config:
            return await interaction.followup.send(
                "❌ TempVC is not configured on this server!", ephemeral=True
            )

        config.owner_warnings.pop(member.id, None)

        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "🔓 Penalty Removed",
            f"Administrator {interaction.user.mention} has removed the penalty and warning strikes for {member.mention}.",
            color=0x57F287
        )

        result = db.get_by_owner(interaction.guild_id, member.id)
        if result:
            channel_id, _ = result
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                from utils.channel_utils import grant_owner_perms
                try:
                    await grant_owner_perms(channel, member)
                except discord.HTTPException:
                    pass
                return await interaction.followup.send(
                    f"✅ Penalty removed for **{member.display_name}**.\n"
                    f"Their **Mute**, **Deafen**, and **Move Members** controls "
                    f"have been restored in their voice channel.",
                    ephemeral=True,
                )

        await interaction.followup.send(
            f"✅ Strike count cleared for **{member.display_name}**.\n"
            f"*(They don't have an active VC right now — perms will be granted fresh next time they create one.)*",
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
