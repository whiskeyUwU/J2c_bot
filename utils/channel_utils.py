
from __future__ import annotations
import io
from datetime import datetime, timezone
import discord
from utils.database import db, TempChannel


async def create_temp_vc(
    member: discord.Member,
    category: discord.CategoryChannel,
) -> discord.VoiceChannel:

    guild  = member.guild
    config = db.get_config(guild.id)
    memory = db.get_memory(guild.id, member.id)

    # Check if this owner is currently under a moderation penalty
    is_penalized = config is not None and member.id in config.penalized_owners

    # Determine channel name: use memory if the user had a custom name
    default_name = f"🎙️ {member.display_name}'s VC"
    name = (memory.name if memory and memory.name else default_name)

    owner_overwrite = discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        mute_members=not is_penalized,
        deafen_members=not is_penalized,
        move_members=not is_penalized,
    )

    # Build base overwrites
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            mute_members=True,
            deafen_members=True,
            move_members=True,
            manage_channels=True,
        ),
        member: owner_overwrite,
    }

    # Apply privacy from memory before channel creation
    if memory and (memory.is_locked or memory.is_hidden):
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=not memory.is_hidden,
            connect=False,
            speak=True,
        )

    # Pre-apply trusted and blocked user overwrites from memory
    if memory:
        for uid in memory.trusted_users:
            target = guild.get_member(uid)
            if target:
                overwrites[target] = discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True
                )
        for uid in memory.blocked_users:
            target = guild.get_member(uid)
            if target:
                overwrites[target] = discord.PermissionOverwrite(
                    view_channel=False, connect=False, speak=False
                )

    channel = await guild.create_voice_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        user_limit=memory.user_limit if memory else 0,
        rtc_region=memory.region if memory else None,
        reason=f"TempVC: Temp VC for {member}",
    )

    if is_penalized:
        try:
            await channel.send(
                f"🚫 {member.mention} — your voice channel moderation controls "
                f"(**Mute**, **Deafen**, **Move**) are still **suspended** due to a previous penalty.\n"
                f"Contact a server admin or moderator to have them restored (`/tempvc-remove-penalty`)."
            )
        except discord.HTTPException:
            pass

    return channel


async def grant_owner_perms(
    channel: discord.VoiceChannel, member: discord.Member
) -> None:

    await channel.set_permissions(
        member,
        view_channel=True,
        connect=True,
        speak=True,
        mute_members=True,
        deafen_members=True,
        move_members=True,
        reason="TempVC: Ownership grant",
    )


async def revoke_owner_perms(
    channel: discord.VoiceChannel, member: discord.Member
) -> None:

    await channel.set_permissions(
        member,
        view_channel=True,
        connect=True,
        speak=True,
        mute_members=False,
        deafen_members=False,
        move_members=False,
        reason="TempVC: Ownership revoked",
    )


async def refresh_panel(
    client: discord.Client,
    guild: discord.Guild,
    ch_data: TempChannel,
    channel: discord.VoiceChannel,
) -> None:

    if not ch_data.panel_message_id or not ch_data.panel_channel_id:
        return

    panel_ch = guild.get_channel(ch_data.panel_channel_id)
    if not panel_ch:
        return

    try:
        msg = await panel_ch.fetch_message(ch_data.panel_message_id)
        from utils.panel_builder import build_embed
        await msg.edit(embed=build_embed(channel, ch_data))
    except (discord.NotFound, discord.HTTPException):
        pass


async def _host_html_online(html_content: str, filename: str) -> str | None:
    """Upload the HTML file to 0x0.st and return a direct browser URL."""
    try:
        import aiohttp
        form = aiohttp.FormData()
        form.add_field(
            "file",
            html_content.encode("utf-8"),
            filename=filename,
            content_type="text/html; charset=utf-8",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://0x0.st",
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
    except Exception:
        pass
    return None


async def _upload_html_transcript(
    guild: discord.Guild,
    ch_data: TempChannel,
    vc: discord.VoiceChannel,
    bot=None,
) -> None:
    """Generate an HTML transcript using chat-exporter and upload to the log channel."""
    config = db.get_config(guild.id)
    if not config or not config.log_channel_id:
        return
    log_ch = guild.get_channel(config.log_channel_id)
    if not log_ch:
        return

    try:
        import chat_exporter
        transcript = await chat_exporter.export(
            vc,
            limit=None,
            bot=bot,
            military_time=True,
        )
    except Exception:
        transcript = None

    if not transcript:
        return

    safe_name = (
        ch_data.name
        .replace("\U0001f399\ufe0f", "")  # strip 🎙️
        .replace(" ", "-")
        .strip("-")
        .lower()
        or "vc"
    )
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"transcript-{safe_name}-{date_str}.html"

    # Try to host online for a direct browser link
    transcript_url = await _host_html_online(transcript, filename)

    embed = discord.Embed(
        title="📋 Voice Chat Transcript",
        color=0x5865F2,
    )
    embed.add_field(name="Channel", value=ch_data.name, inline=True)
    embed.add_field(name="Owner", value=f"<@{ch_data.owner_id}>", inline=True)
    embed.timestamp = discord.utils.utcnow()

    if transcript_url:
        # Post as a clickable link — opens directly in browser, no file attached!
        embed.description = (
            f"### [🔗 Click here to view the transcript]({transcript_url})\n"
            f"Opens directly in your browser — no download needed."
        )
        embed.set_footer(text="Hosted on 0x0.st • Link valid for ~30 days")
        try:
            await log_ch.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass
    else:
        # Fallback: attach the file if hosting fails
        embed.description = (
            f"Transcript saved — download the `.html` file and open it in your browser."
        )
        embed.set_footer(text="Open the .html file in any browser to view")
        file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=filename)
        try:
            await log_ch.send(embed=embed, file=file)
        except (discord.Forbidden, discord.HTTPException):
            pass


async def cleanup(
    channel_id: int,
    ch_data: TempChannel,
    guild: discord.Guild,
    bot=None,
) -> None:

    from utils.log_utils import log_to_admin_channel
    owner_mention = f"<@{ch_data.owner_id}>"
    await log_to_admin_channel(
        guild,
        "🗑️ Temp VC Deleted",
        f"Voice channel **{ch_data.name}** has been cleaned up and deleted.",
        color=0xE74C3C,
        fields=[
            {"name": "Owner",      "value": owner_mention,    "inline": True},
            {"name": "Channel ID", "value": str(channel_id),  "inline": True},
        ]
    )

    # ── Save owner's settings to memory before wiping the record ──────────
    db.save_memory(guild.id, ch_data.owner_id, ch_data)

    db.delete(channel_id)

    if ch_data.waiting_room_id:
        wr = guild.get_channel(ch_data.waiting_room_id)
        if wr:
            try:
                await wr.delete(reason="TempVC: Parent VC deleted")
            except discord.HTTPException:
                pass

    if ch_data.chat_channel_id:
        cc = guild.get_channel(ch_data.chat_channel_id)
        if cc:
            try:
                await cc.delete(reason="TempVC: Parent VC deleted")
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

    # Generate and upload HTML transcript BEFORE deleting the voice channel
    vc = guild.get_channel(channel_id)
    if vc:
        await _upload_html_transcript(guild, ch_data, vc, bot=bot)

        try:
            await vc.delete(reason="TempVC: Temp VC cleaned up")
        except discord.HTTPException:
            pass
