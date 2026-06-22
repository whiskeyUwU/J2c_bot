
from __future__ import annotations
import asyncio
import discord
from discord.ext import commands, tasks

from utils.database import db, TempChannel
from utils.channel_utils import (
    create_temp_vc,
    grant_owner_perms,
    refresh_panel,
    cleanup,
)
from utils.panel_builder import build_embed

class VoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.auto_save.start()

    def cog_unload(self) -> None:
        self.auto_save.cancel()

    @tasks.loop(seconds=30)
    async def auto_save(self) -> None:

        db.save()

    @auto_save.before_loop
    async def before_auto_save(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:

        stale_ids: list[int] = []

        for ch_id, ch_data in list(db._channels.items()):
            guild = self.bot.get_guild(ch_data.guild_id)
            if not guild:
                stale_ids.append(ch_id)
                continue

            channel = guild.get_channel(ch_id)
            if channel:
                if len(channel.members) > 0:
                    continue

            if ch_data.waiting_room_id:
                wr = guild.get_channel(ch_data.waiting_room_id)
                if wr:
                    try:
                        await wr.delete(reason="TempVC: Stale waiting room cleanup on restart")
                    except discord.HTTPException:
                        pass

            if ch_data.chat_channel_id:
                cc = guild.get_channel(ch_data.chat_channel_id)
                if cc:
                    try:
                        await cc.delete(reason="TempVC: Stale chat channel cleanup on restart")
                    except discord.HTTPException:
                        pass

            if ch_data.panel_message_id and ch_data.panel_channel_id:
                panel_ch = guild.get_channel(ch_data.panel_channel_id)
                if panel_ch:
                    try:
                        msg = await panel_ch.fetch_message(ch_data.panel_message_id)
                        await msg.delete()
                    except discord.HTTPException:
                        pass

            for user_id in ch_data.muted_by_owner:
                member = guild.get_member(user_id)
                if member and member.voice and member.voice.mute:
                    try:
                        await member.edit(
                            mute=False,
                            reason="TempVC: Bot restarted — clearing stale owner mute",
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            stale_ids.append(ch_id)

        for ch_id in stale_ids:
            db.delete(ch_id)

        if stale_ids:
            print(f"🧹  Cleaned up {len(stale_ids)} stale temp VC(s) on startup.")
        else:
            print("✅  No stale temp VCs found.")

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:

        config = db.get_config(after.guild.id)
        if not config:
            return

        before_mute = before.voice.mute if (before.voice and before.voice.channel) else False
        after_mute  = after.voice.mute  if (after.voice  and after.voice.channel)  else False

        if before_mute == after_mute:
            return

        in_temp_vc = (
            after.voice
            and after.voice.channel
            and db.exists(after.voice.channel.id)
        )
        if in_temp_vc:
            return

        if after_mute and not before_mute:

            config.admin_muted.add(after.id)
        elif not after_mute and before_mute:

            config.admin_muted.discard(after.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        config = db.get_config(member.guild.id)
        if not config:
            return

        guild = member.guild

        if (
            after.channel
            and after.channel.id == config.jtc_channel_id
            and (before.channel is None or before.channel.id != config.jtc_channel_id)
        ):
            await self._on_jtc_join(member, guild, config)


        if (
            before.channel
            and after.channel
            and before.channel.id == after.channel.id
            and before.mute != after.mute
        ):
            in_temp = db.exists(after.channel.id)

            if in_temp:

                ch_data = db.get(after.channel.id)
                if ch_data:
                    if after.mute and not before.mute:

                        ch_data.muted_by_owner.add(member.id)
                        actor = await self._get_mute_update_actor(guild, member.id, is_mute=True)
                        actor_mention = actor.mention if actor else "Owner / Admin"
                        from utils.log_utils import log_to_admin_channel
                        await log_to_admin_channel(
                            guild,
                            "🎙️ User Muted",
                            f"{member.mention} was server-muted by {actor_mention} in {after.channel.mention}.",
                            color=0xE67E22
                        )

                    elif not after.mute and before.mute:

                        if member.id in config.admin_muted:
                            await self._handle_admin_mute_bypass(
                                member, after.channel, ch_data, config, guild
                            )
                        else:

                            ch_data.muted_by_owner.discard(member.id)
                            actor = await self._get_mute_update_actor(guild, member.id, is_mute=False)
                            actor_mention = actor.mention if actor else "Owner / Admin"
                            from utils.log_utils import log_to_admin_channel
                            await log_to_admin_channel(
                                guild,
                                "🎙️ User Unmuted",
                               f"{member.mention} was server-unmuted by {actor_mention} in {after.channel.mention}.",
                                color=0x2ECC71
                            )

            else:

                if after.mute and not before.mute:
                    config.admin_muted.add(member.id)
                elif not after.mute and before.mute:
                    config.admin_muted.discard(member.id)

        if (
            before.channel
            and (after.channel is None or after.channel.id != before.channel.id)
            and db.exists(before.channel.id)
        ):
            await self._on_leave_temp_vc(member, before.channel, guild)

        if (
            after.channel
            and (before.channel is None or before.channel.id != after.channel.id)
            and db.exists(after.channel.id)
        ):
            await self._on_join_temp_vc(member, after.channel, config)

    async def _on_jtc_join(
        self,
        member: discord.Member,
        guild: discord.Guild,
        config,
    ) -> None:
        category = guild.get_channel(config.category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            return

        try:
            channel = await create_temp_vc(member, category)
        except discord.Forbidden:
            return

        try:
            await member.move_to(channel, reason="TempVC: Joined JTC")
        except discord.HTTPException:
            await channel.delete()
            return

        # ── Restore saved memory into TempChannel record ──────────────────
        memory = db.get_memory(guild.id, member.id)

        ch_data = TempChannel(
            owner_id=member.id,
            guild_id=guild.id,
            name=channel.name,
            user_limit=memory.user_limit if memory else 0,
            is_locked=memory.is_locked if memory else False,
            is_hidden=memory.is_hidden if memory else False,
            region=memory.region if memory else None,
            trusted_users=set(memory.trusted_users) if memory else set(),
            blocked_users=set(memory.blocked_users) if memory else set(),
            muted_by_owner=set(memory.muted_by_owner) if memory else set(),
        )
        db.create(channel.id, ch_data)

        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            guild,
            "🎙️ Temp VC Created",
            f"Voice channel {channel.mention} has been created.",
            color=0x3498DB,
            fields=[
                {"name": "Owner", "value": member.mention, "inline": True},
                {"name": "Channel ID", "value": str(channel.id), "inline": True},
            ]
        )

        from cogs.panel_cog import TempVCControlView
        embed = build_embed(channel, ch_data)
        view  = TempVCControlView()
        view.customize_for_client(self.bot)
        try:
            file = discord.File("interface.png", filename="interface.png")
            msg = await channel.send(
                content=f"🎙️ {member.mention}'s Voice Channel Controls",
                file=file,
                embed=embed,
                view=view,
            )
            ch_data.panel_message_id = msg.id
            ch_data.panel_channel_id = channel.id
            db.save()
        except discord.HTTPException:
            pass

        # ── Send restoration notice if settings were loaded ───────────────
        if memory:
            fields: list[tuple[str, str]] = []

            if memory.name:
                fields.append(("🏷️  Name",    f"`{memory.name}`"))
            if memory.user_limit:
                fields.append(("👥  Limit",   f"`{memory.user_limit} users`"))
            if memory.is_hidden:
                fields.append(("🙈  Privacy", "`Hidden`"))
            elif memory.is_locked:
                fields.append(("🔒  Privacy", "`Locked`"))
            if memory.region:
                fields.append(("🌐  Region",  f"`{memory.region}`"))
            if memory.trusted_users:
                n = len(memory.trusted_users)
                fields.append(("✅  Trusted", f"`{n} user{'s' if n != 1 else ''}`"))
            if memory.blocked_users:
                n = len(memory.blocked_users)
                fields.append(("🚫  Blocked", f"`{n} user{'s' if n != 1 else ''}`"))
            if memory.muted_by_owner:
                n = len(memory.muted_by_owner)
                fields.append(("🔇  Muted",   f"`{n} user{'s' if n != 1 else ''}`"))

            if fields:
                restore_embed = discord.Embed(
                    title="💾  Settings Restored",
                    description=(
                        f"Welcome back, {member.mention}!\n"
                        f"Your previous channel preferences have been applied automatically."
                    ),
                    color=0x5865F2,
                )
                for name, value in fields:
                    restore_embed.add_field(name=name, value=value, inline=True)
                restore_embed.set_footer(
                    text="This message will disappear in 20 seconds  •  TempVC Memory",
                )
                try:
                    await channel.send(embed=restore_embed, delete_after=20)
                except discord.HTTPException:
                    pass

    async def _on_leave_temp_vc(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        guild: discord.Guild,
    ) -> None:
        ch_data = db.get(channel.id)
        if not ch_data:
            return

        if member.id in ch_data.muted_by_owner:
            asyncio.create_task(
                member.edit(mute=False, reason="TempVC: Left VC — unmuting (will re-mute on rejoin)")
            )

        if len(channel.members) == 0:
            await cleanup(channel.id, ch_data, guild, bot=self.bot)

    async def _on_join_temp_vc(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        config,
    ) -> None:
        ch_data = db.get(channel.id)
        if not ch_data:
            return

        if member.voice and member.voice.mute:
            if member.id not in ch_data.muted_by_owner:
                if config:
                    config.admin_muted.add(member.id)

        elif member.id in ch_data.muted_by_owner and member.id != ch_data.owner_id:
            try:
                await member.edit(mute=True, reason="TempVC: Re-muting (was muted by VC owner)")
            except (discord.Forbidden, discord.HTTPException):
                pass

        if member.id in ch_data.blocked_users and member.id != ch_data.owner_id:
            try:
                await member.move_to(None, reason="TempVC: Blocked user")
            except discord.HTTPException:
                pass

    async def _get_mute_update_actor(
        self,
        guild: discord.Guild,
        target_id: int,
        is_mute: bool,
    ) -> discord.Member | None:
        try:
            async for entry in guild.audit_logs(
                limit=5,
                action=discord.AuditLogAction.member_update,
            ):
                if entry.target.id != target_id:
                    continue
                before_mute = getattr(entry.before, "mute", None)
                after_mute  = getattr(entry.after,  "mute", None)
                if is_mute and before_mute is False and after_mute is True:
                    return guild.get_member(entry.user.id)
                elif not is_mute and before_mute is True and after_mute is False:
                    return guild.get_member(entry.user.id)
                break
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    async def _get_unmute_actor(
        self,
        guild: discord.Guild,
        target_id: int,
    ) -> discord.Member | None:
        return await self._get_mute_update_actor(guild, target_id, is_mute=False)

    async def _handle_admin_mute_bypass(
        self,
        muted_user: discord.Member,
        channel: discord.VoiceChannel,
        ch_data,
        config,
        guild: discord.Guild,
    ) -> None:

        actor = await self._get_unmute_actor(guild, muted_user.id)

        if actor is not None:
            perms = actor.guild_permissions
            if perms.administrator or perms.mute_members:
                config.admin_muted.discard(muted_user.id)
                return

        try:
            await muted_user.edit(
                mute=True,
                reason="TempVC: Cannot override admin/mod server mute",
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        owner_id      = ch_data.owner_id
        owner         = guild.get_member(owner_id)
        owner_mention = owner.mention if owner else f"<@{owner_id}>"

        strikes = config.owner_warnings.get(owner_id, 0) + 1
        config.owner_warnings[owner_id] = strikes

        if strikes == 1:
            msg = (
                f"⚠️ **Warning [1/2]** — {owner_mention}\n"
                f"**{muted_user.display_name}** has been **server-muted by an admin or moderator** "
                f"and you are not allowed to unmute them.\n"
                f"The mute has been re-applied automatically.\n"
                f"*Attempting this again will result in your voice channel "
                f"moderation controls being permanently removed.*"
            )
            try:
                await channel.send(msg)
            except discord.HTTPException:
                pass
            if owner:
                try:
                    await owner.send(msg)
                except discord.Forbidden:
                    pass

            from utils.log_utils import log_to_admin_channel
            await log_to_admin_channel(
                guild,
                "⚠️ Warning Strike Issued",
                f"VC owner {owner_mention} attempted to unmute {muted_user.mention} who was admin-muted. Warn strike **[1/2]** issued in {channel.mention}.",
                color=0xF1C40F
            )

        else:
            if owner:
                try:
                    await channel.set_permissions(
                        owner,
                        mute_members=False,
                        deafen_members=False,
                        move_members=False,
                        reason="TempVC: Penalty — repeatedly bypassed admin mute",
                    )
                except discord.HTTPException:
                    pass

            msg = (
                f"🚫 **Penalty Applied** — {owner_mention}\n"
                f"You attempted to unmute **{muted_user.display_name}** "
                f"(server-muted by an admin/mod) **more than once**.\n\n"
                f"Your voice channel moderation powers "
                f"(**Mute Members**, **Deafen Members**, **Move Members**) "
                f"have been **removed** from your channel.\n\n"
                f"Please contact a **server admin or moderator** to have your "
                f"controls restored. They can use `/tempvc-remove-penalty` to do so."
            )
            try:
                await channel.send(msg)
            except discord.HTTPException:
                pass
            if owner:
                try:
                    await owner.send(msg)
                except discord.Forbidden:
                    pass

            from utils.log_utils import log_to_admin_channel
            await log_to_admin_channel(
                guild,
                "🚫 Penalty Applied",
                f"VC owner {owner_mention} repeatedly bypassed an admin mute. Warn strike **[2/2]** issued. Moderation permissions revoked in {channel.mention}.",
                color=0xE74C3C
            )

            config.owner_warnings[owner_id] = 0
            config.penalized_owners.add(owner_id)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
