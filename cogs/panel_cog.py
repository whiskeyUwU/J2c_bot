
from __future__ import annotations
import discord
from discord.ext import commands

from utils.database import db
from utils.channel_utils import (
    grant_owner_perms,
    revoke_owner_perms,
    refresh_panel,
    cleanup,
)
from utils.panel_builder import build_embed, get_button_emoji, build_interface_embed, get_emoji

async def _owner_check(
    interaction: discord.Interaction,
) -> tuple[int | None, discord.VoiceChannel | None, object | None, str | None]:

    if not interaction.message:
        return None, None, None, "❌ This button must be clicked on a control panel message!"

    ch_data = None
    channel_id = None
    for cid, ch in db._channels.items():
        if ch.panel_message_id == interaction.message.id:
            ch_data = ch
            channel_id = cid
            break

    if not ch_data:
        return None, None, None, "❌ This control panel is no longer active because the voice channel has been deleted!"

    if ch_data.owner_id != interaction.user.id:
        return None, None, None, "❌ Only the voice channel owner can use these controls!"

    channel = interaction.guild.get_channel(channel_id)
    if not channel:
        db.delete(channel_id)
        return None, None, None, "❌ Your voice channel no longer exists!"

    return channel_id, channel, ch_data, None

async def _shared_owner_check(
    interaction: discord.Interaction,
) -> tuple[int | None, discord.VoiceChannel | None, object | None, str | None]:

    result = db.get_by_owner(interaction.guild_id, interaction.user.id)
    if not result:
        return None, None, None, (
            "❌ Only the voice channel owner can use these controls!\n"
            "Join the **➕ Join to Create** voice channel first."
        )
    channel_id, ch_data = result
    channel = interaction.guild.get_channel(channel_id)
    if not channel:
        db.delete(channel_id)
        return None, None, None, "❌ Your voice channel no longer exists!"
    return channel_id, channel, ch_data, None

class NameModal(discord.ui.Modal, title="Rename Voice Channel"):
    new_name = discord.ui.TextInput(
        label="New Channel Name",
        placeholder="e.g. Gaming Session",
        min_length=1,
        max_length=100,
    )

    def __init__(self, channel_id: int) -> None:
        super().__init__()
        self._cid = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ch_data = db.get(self._cid)
        channel: discord.VoiceChannel | None = interaction.guild.get_channel(self._cid)
        if not ch_data or not channel:
            return await interaction.response.send_message("❌ Channel not found!", ephemeral=True)

        name = self.new_name.value.strip()
        await channel.edit(name=name, reason="TempVC: Owner renamed channel")
        ch_data.name = name
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "🏷️ Channel Renamed",
            f"Voice channel owner {interaction.user.mention} renamed their channel to **{name}**.",
            color=0x3498DB
        )
        e = get_emoji(interaction.client, "tempvc_ico_name", "🏷️")
        await interaction.response.send_message(f"{e} Channel renamed to **{name}**!", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Set User Limit"):
    limit_value = discord.ui.TextInput(
        label="User Limit  (0 = Unlimited, max 99)",
        placeholder="Enter a number 0–99",
        min_length=1,
        max_length=2,
    )

    def __init__(self, channel_id: int) -> None:
        super().__init__()
        self._cid = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            limit = int(self.limit_value.value.strip())
            if not (0 <= limit <= 99):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Please enter a whole number between **0** and **99**.", ephemeral=True
            )

        ch_data = db.get(self._cid)
        channel: discord.VoiceChannel | None = interaction.guild.get_channel(self._cid)
        if not ch_data or not channel:
            return await interaction.response.send_message("❌ Channel not found!", ephemeral=True)

        await channel.edit(user_limit=limit, reason="TempVC: Owner set user limit")
        ch_data.user_limit = limit
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        label = f"**{limit}**" if limit else "**Unlimited**"
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "👥 User Limit Updated",
            f"Voice channel owner {interaction.user.mention} set user limit to **{label}** in {channel.mention}.",
            color=0x3498DB
        )
        e = get_emoji(interaction.client, "tempvc_ico_limit", "👥")
        await interaction.response.send_message(f"{e} User limit set to {label}!", ephemeral=True)

_REGION_OPTIONS = [
    discord.SelectOption(label="Automatic",    value="auto",        emoji="🌍", description="Let Discord choose the best region"),
    discord.SelectOption(label="US East",      value="us-east",     emoji="🇺🇸"),
    discord.SelectOption(label="US West",      value="us-west",     emoji="🇺🇸"),
    discord.SelectOption(label="US Central",   value="us-central",  emoji="🇺🇸"),
    discord.SelectOption(label="US South",     value="us-south",    emoji="🇺🇸"),
    discord.SelectOption(label="Europe",       value="europe",      emoji="🇪🇺"),
    discord.SelectOption(label="Brazil",       value="brazil",      emoji="🇧🇷"),
    discord.SelectOption(label="Singapore",    value="singapore",   emoji="🇸🇬"),
    discord.SelectOption(label="South Africa", value="southafrica", emoji="🇿🇦"),
    discord.SelectOption(label="Sydney",       value="sydney",      emoji="🇦🇺"),
    discord.SelectOption(label="Hong Kong",    value="hongkong",    emoji="🇭🇰"),
    discord.SelectOption(label="Russia",       value="russia",      emoji="🇷🇺"),
    discord.SelectOption(label="Japan",        value="japan",       emoji="🇯🇵"),
    discord.SelectOption(label="India",        value="india",       emoji="🇮🇳"),
]

class RegionSelectView(discord.ui.View):
    def __init__(self, channel_id: int) -> None:
        super().__init__(timeout=60)
        self._cid = channel_id

    @discord.ui.select(
        placeholder="🌐 Choose a voice region…",
        options=_REGION_OPTIONS,
        min_values=1,
        max_values=1,
    )
    async def region_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        value    = select.values[0]
        ch_data  = db.get(self._cid)
        channel: discord.VoiceChannel | None = interaction.guild.get_channel(self._cid)

        if not ch_data or not channel:
            return await interaction.response.edit_message(
                content="❌ Channel not found!", view=None
            )

        rtc_region = None if value == "auto" else value
        await channel.edit(rtc_region=rtc_region, reason="TempVC: Owner changed region")
        ch_data.region = rtc_region
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)

        label = next((o.label for o in _REGION_OPTIONS if o.value == value), value)
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "🌐 Region Updated",
            f"Voice channel owner {interaction.user.mention} set voice region to **{label}** in {channel.mention}.",
            color=0x3498DB
        )
        e_region = get_emoji(interaction.client, "tempvc_ico_region", "🌐")
        await interaction.response.edit_message(
            content=f"{e_region} Region changed to **{label}**!", view=None
        )


class PrivacySelectView(discord.ui.View):
    def __init__(self, channel_id: int) -> None:
        super().__init__(timeout=60)
        self._cid = channel_id

    @discord.ui.select(
        placeholder="🛡️ Choose a privacy mode…",
        options=[
            discord.SelectOption(
                label="Public",
                value="public",
                emoji="🔓",
                description="Anyone can see and join your channel",
            ),
            discord.SelectOption(
                label="Locked",
                value="locked",
                emoji="🔒",
                description="Visible to all, but only trusted/invited can join",
            ),
            discord.SelectOption(
                label="Hidden",
                value="hidden",
                emoji="🙈",
                description="Invisible to everyone — only trusted/invited can see & join",
            ),
        ],
        min_values=1,
        max_values=1,
    )
    async def privacy_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        value    = select.values[0]
        ch_data  = db.get(self._cid)
        channel: discord.VoiceChannel | None = interaction.guild.get_channel(self._cid)

        if not ch_data or not channel:
            return await interaction.response.edit_message(
                content="❌ Channel not found!", view=None
            )

        default_role = interaction.guild.default_role

        if value == "public":
            await channel.set_permissions(
                default_role, view_channel=True, connect=True,
                reason="TempVC: Set to Public"
            )
            ch_data.is_locked = False
            ch_data.is_hidden  = False
            e_pub = get_emoji(interaction.client, "tempvc_ico_privacy", "🔓")
            status = f"{e_pub} Channel is now **Public** — anyone can see and join."

        elif value == "locked":
            await channel.set_permissions(
                default_role, view_channel=True, connect=False,
                reason="TempVC: Set to Locked"
            )
            ch_data.is_locked = True
            ch_data.is_hidden  = False
            e_lock = get_emoji(interaction.client, "tempvc_ico_privacy", "🔒")
            status = f"{e_lock} Channel is now **Locked** — visible but only trusted/invited users can join."

        elif value == "hidden":
            await channel.set_permissions(
                default_role, view_channel=False, connect=False,
                reason="TempVC: Set to Hidden"
            )
            ch_data.is_locked = True
            ch_data.is_hidden  = True
            e_hide = get_emoji(interaction.client, "tempvc_ico_privacy", "🙈")
            status = f"{e_hide} Channel is now **Hidden** — invisible to everyone except trusted/invited users."

        else:
            return await interaction.response.edit_message(content="❌ Unknown option.", view=None)

        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        label_map = {"public": "Public", "locked": "Locked", "hidden": "Hidden"}
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "🛡️ Channel Privacy Changed",
            f"Voice channel owner {interaction.user.mention} set privacy to **{label_map[value]}** in {channel.mention}.",
            color=0x3498DB,
        )
        await interaction.response.edit_message(content=status, view=None)

class UserActionView(discord.ui.View):

    _PROMPTS: dict[str, str] = {
        "trust":    "✅ Select a user to **trust** (they bypass the channel lock)",
        "untrust":  "❎ Select a user to **untrust**",
        "invite":   "📨 Select a user to **invite** (they'll receive a DM notification)",
        "kick":     "👢 Select a user to **kick** from your channel",
        "block":    "🚫 Select a user to **block** (they can no longer join)",
        "unblock":  "✔️ Select a user to **unblock**",
        "transfer": "🔄 Select a user to **transfer ownership** to (must be in your VC)",
    }

    def __init__(self, action: str, channel_id: int) -> None:
        super().__init__(timeout=60)
        self._action = action
        self._cid    = channel_id

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select a member…",
        min_values=1,
        max_values=1,
    )
    async def user_select(
        self, interaction: discord.Interaction, select: discord.ui.UserSelect
    ) -> None:
        target: discord.Member = select.values[0]
        ch_data  = db.get(self._cid)
        channel: discord.VoiceChannel | None = interaction.guild.get_channel(self._cid)

        if not ch_data or not channel:
            return await interaction.response.edit_message(
                content="❌ Channel no longer exists!", view=None
            )

        if target.id == interaction.user.id:
            return await interaction.response.edit_message(content="❌ You can't target yourself!", view=None)
        if target.bot:
            return await interaction.response.edit_message(content="❌ You can't target bots!", view=None)

        action = self._action
        msg    = ""

        if action == "trust":
            ch_data.trusted_users.add(target.id)
            ch_data.blocked_users.discard(target.id)
            await channel.set_permissions(
                target, view_channel=True, connect=True, speak=True,
                reason="TempVC: Trusted by owner"
            )
            e = get_emoji(interaction.client, "tempvc_ico_trust", "✅")
            msg = f"{e} **{target.display_name}** is now trusted and can bypass the channel lock."

        elif action == "untrust":
            if target.id not in ch_data.trusted_users:
                return await interaction.response.edit_message(
                    content=f"❌ **{target.display_name}** is not in your trust list!", view=None
                )
            ch_data.trusted_users.discard(target.id)

            if target.id in ch_data.blocked_users:
                await channel.set_permissions(target, connect=False, speak=False, view_channel=False)
            else:
                await channel.set_permissions(target, overwrite=None)
            e = get_emoji(interaction.client, "tempvc_ico_untrust", "❎")
            msg = f"{e} **{target.display_name}** has been untrusted."

        elif action == "invite":
            ch_data.invited_users.add(target.id)
            await channel.set_permissions(
                target, view_channel=True, connect=True, speak=True,
                reason="TempVC: Invited by owner"
            )

            try:
                await target.send(
                    f"📨 **{interaction.user.display_name}** has invited you to join "
                    f"their voice channel **{channel.name}** in **{interaction.guild.name}**!"
                )
            except discord.Forbidden:
                pass
            e = get_emoji(interaction.client, "tempvc_ico_invite", "📨")
            msg = f"{e} **{target.display_name}** has been invited and can now join!"

        elif action == "kick":
            if not target.voice or target.voice.channel != channel:
                return await interaction.response.edit_message(
                    content=f"❌ **{target.display_name}** is not in your channel!", view=None
                )
            try:
                await target.move_to(None, reason="TempVC: Kicked by VC owner")
            except discord.Forbidden:
                return await interaction.response.edit_message(
                    content="❌ Couldn't kick — check the bot's permissions!", view=None
                )
            e = get_emoji(interaction.client, "tempvc_ico_kick", "👢")
            msg = f"{e} **{target.display_name}** has been kicked from the channel."

        elif action == "block":
            ch_data.blocked_users.add(target.id)
            ch_data.trusted_users.discard(target.id)
            ch_data.invited_users.discard(target.id)

            await channel.set_permissions(
                target,
                view_channel=False,
                connect=False,
                speak=False,
                reason="TempVC: Blocked by owner",
            )

            if target.voice and target.voice.channel == channel:
                try:
                    await target.move_to(None, reason="TempVC: Blocked — removing from VC")
                except discord.HTTPException:
                    pass
            e = get_emoji(interaction.client, "tempvc_ico_block", "🚫")
            msg = f"{e} **{target.display_name}** has been blocked from your channel."

        elif action == "unblock":
            if target.id not in ch_data.blocked_users:
                return await interaction.response.edit_message(
                    content=f"❌ **{target.display_name}** is not blocked!", view=None
                )
            ch_data.blocked_users.discard(target.id)
            if target.id in ch_data.trusted_users:
                await channel.set_permissions(target, view_channel=True, connect=True, speak=True)
            else:
                await channel.set_permissions(target, overwrite=None)
            e = get_emoji(interaction.client, "tempvc_ico_unblock", "✔️")
            msg = f"{e} **{target.display_name}** has been unblocked."

        elif action == "transfer":
            if not target.voice or target.voice.channel != channel:
                return await interaction.response.edit_message(
                    content=f"❌ **{target.display_name}** must be in your channel to receive ownership!",
                    view=None,
                )
            old_owner = interaction.user
            ch_data.owner_id = target.id
            await revoke_owner_perms(channel, old_owner)
            await grant_owner_perms(channel, target)
            e = get_emoji(interaction.client, "tempvc_ico_transfer", "🔄")
            msg = f"{e} Ownership successfully transferred to **{target.display_name}**!"

        else:
            msg = "❌ Unknown action."

        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        icon_map = {
            "trust": ("tempvc_ico_trust", "✅"),
            "untrust": ("tempvc_ico_untrust", "❎"),
            "invite": ("tempvc_ico_invite", "📨"),
            "kick": ("tempvc_ico_kick", "👢"),
            "block": ("tempvc_ico_block", "🚫"),
            "unblock": ("tempvc_ico_unblock", "✔️"),
            "transfer": ("tempvc_ico_transfer", "🔄"),
        }
        _iname, _ifallback = icon_map.get(action, ("tempvc_ico_name", "⚙️"))
        emoji = get_emoji(interaction.client, _iname, _ifallback)
        await log_to_admin_channel(
            interaction.guild,
            f"{emoji} Member Action: {action.capitalize()}",
            f"Voice channel owner {interaction.user.mention} performed **{action}** on {target.mention} in {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.edit_message(content=msg, view=None)

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, channel_id: int, ch_data) -> None:
        super().__init__(timeout=30)
        self._cid     = channel_id
        self._ch_data = ch_data

    @discord.ui.button(label="Yes, Delete It", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="🗑️ Deleting your voice channel…", view=None
        )
        await cleanup(self._cid, self._ch_data, interaction.guild, bot=interaction.client)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="✅ Deletion cancelled.", view=None)

class TempVCControlView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    def customize_for_client(self, client: discord.Client) -> None:
        fallbacks = {
            "name": ("tempvc_ico_name", "🏷️"),
            "limit": ("tempvc_ico_limit", "👥"),
            "privacy": ("tempvc_ico_privacy", "🛡️"),
            "waiting": ("tempvc_ico_waiting", "⏳"),
            "chat": ("tempvc_ico_chat", "💬"),
            "trust": ("tempvc_ico_trust", "✅"),
            "untrust": ("tempvc_ico_untrust", "❌"),
            "invite": ("tempvc_ico_invite", "📨"),
            "kick": ("tempvc_ico_kick", "👢"),
            "region": ("tempvc_ico_region", "🌐"),
            "block": ("tempvc_ico_block", "🚫"),
            "unblock": ("tempvc_ico_unblock", "✔️"),
            "claim": ("tempvc_ico_claim", "👑"),
            "transfer": ("tempvc_ico_transfer", "🔄"),
            "delete": ("tempvc_ico_delete", "🗑️"),
        }
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id:
                parts = item.custom_id.split(":")
                if len(parts) == 2:
                    action = parts[1]
                    if action in fallbacks:
                        emoji_name, fallback_emoji = fallbacks[action]
                        item.emoji = get_button_emoji(client, emoji_name, fallback_emoji)
                        item.label = None


    @discord.ui.button(label="NAME",         emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="tempvc:name",    row=0)
    async def btn_name(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_modal(NameModal(cid))

    @discord.ui.button(label="LIMIT",        emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tempvc:limit",   row=0)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_modal(LimitModal(cid))

    @discord.ui.button(label="PRIVACY",      emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="tempvc:privacy", row=0)
    async def btn_privacy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            "🛡️ **Channel Privacy** — Choose how visible and accessible your channel is.",
            view=PrivacySelectView(cid), ephemeral=True,
        )

    @discord.ui.button(label="WAITING ROOM", emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="tempvc:waiting", row=0)
    async def btn_waiting(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)

        if ch_data.waiting_room_id:

            wr = interaction.guild.get_channel(ch_data.waiting_room_id)
            if wr:
                try:
                    await wr.delete(reason="TempVC: Owner disabled waiting room")
                except discord.HTTPException:
                    pass
            ch_data.waiting_room_id = None
            status = "⏳ Waiting room has been **removed**."
        else:

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=False
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    view_channel=True, connect=True, move_members=True
                ),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True, connect=True, move_members=True
                ),
            }
            try:
                wr = await interaction.guild.create_voice_channel(
                    name="⏳ Waiting Room",
                    category=channel.category,
                    overwrites=overwrites,
                    reason="TempVC: Owner enabled waiting room",
                )
                ch_data.waiting_room_id = wr.id
                status = f"⏳ Waiting room created! Users can wait in {wr.mention} and you can drag them in."
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "❌ Couldn't create waiting room — check bot permissions!", ephemeral=True
                )

        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        action_str = f"created waiting room: {wr.mention}" if ch_data.waiting_room_id else "removed waiting room"
        await log_to_admin_channel(
            interaction.guild,
            "⏳ Waiting Room Toggled",
            f"Voice channel owner {interaction.user.mention} {action_str} for {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="CHAT",         emoji="💬", style=discord.ButtonStyle.secondary, custom_id="tempvc:chat",    row=0)
    async def btn_chat(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)

        if ch_data.chat_channel_id:
            cc = interaction.guild.get_channel(ch_data.chat_channel_id)
            if cc:
                try:
                    await cc.delete(reason="TempVC: Owner disabled chat")
                except discord.HTTPException:
                    pass
            ch_data.chat_channel_id = None
            status = "💬 Text chat has been **removed**."
        else:
            safe_name = (
                channel.name
                .lower()
                .replace("🎙️", "")
                .replace(" ", "-")
                .replace("'", "")
                .strip("-") or "vc-chat"
            )
            chat_perms = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=not ch_data.is_locked,
                    send_messages=not ch_data.is_locked,
                    read_message_history=True,
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True
                ),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True
                ),
            }
            try:
                cc = await interaction.guild.create_text_channel(
                    name=f"💬-{safe_name}",
                    category=channel.category,
                    overwrites=chat_perms,
                    reason="TempVC: Owner enabled chat",
                )
                ch_data.chat_channel_id = cc.id
                status = f"💬 Text chat created: {cc.mention}"
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "❌ Couldn't create chat channel — check bot permissions!", ephemeral=True
                )

        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        action_str = f"created text chat: {cc.mention}" if ch_data.chat_channel_id else "removed text chat"
        await log_to_admin_channel(
            interaction.guild,
            "💬 Chat Channel Toggled",
            f"Voice channel owner {interaction.user.mention} {action_str} for {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="TRUST",   emoji="✅", style=discord.ButtonStyle.secondary, custom_id="tempvc:trust",   row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_trust', '✅')} **Trust a User** — Trusted users can join even when the channel is locked.",
            view=UserActionView("trust", cid), ephemeral=True,
        )

    @discord.ui.button(label="UNTRUST", emoji="❎", style=discord.ButtonStyle.secondary, custom_id="tempvc:untrust", row=1)
    async def btn_untrust(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_untrust', '❎')} **Untrust a User** — Remove a user's trusted status.",
            view=UserActionView("untrust", cid), ephemeral=True,
        )

    @discord.ui.button(label="INVITE",  emoji="📨", style=discord.ButtonStyle.secondary, custom_id="tempvc:invite",  row=1)
    async def btn_invite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_invite', '📨')} **Invite a User** — They'll receive a DM and can join even if the channel is locked.",
            view=UserActionView("invite", cid), ephemeral=True,
        )

    @discord.ui.button(label="KICK",    emoji="👢", style=discord.ButtonStyle.danger,    custom_id="tempvc:kick",    row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)

        vc_members = [m for m in channel.members if m.id != interaction.user.id and not m.bot]
        if not vc_members:
            return await interaction.response.send_message(
                "❌ There's nobody else in your channel to kick!\n"
                "*(You can also drag members out directly with your native Move Members permission.)*",
                ephemeral=True,
            )
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_kick', '👢')} **Kick a User** — Disconnect them from your channel.\n*(You can also right-click any member and choose Disconnect.)*",
            view=UserActionView("kick", cid), ephemeral=True,
        )

    @discord.ui.button(label="REGION",  emoji="🌐", style=discord.ButtonStyle.secondary, custom_id="tempvc:region",  row=1)
    async def btn_region(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_region', '🌐')} **Change Voice Region** — Pick a specific server region.",
            view=RegionSelectView(cid), ephemeral=True,
        )

    @discord.ui.button(label="BLOCK",    emoji="🚫", style=discord.ButtonStyle.danger,     custom_id="tempvc:block",    row=2)
    async def btn_block(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_block', '🚫')} **Block a User** — They won't be able to join your channel.",
            view=UserActionView("block", cid), ephemeral=True,
        )

    @discord.ui.button(label="UNBLOCK",  emoji="✔️", style=discord.ButtonStyle.secondary,  custom_id="tempvc:unblock",  row=2)
    async def btn_unblock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_unblock', '✔️')} **Unblock a User** — Allow a previously blocked user to join.",
            view=UserActionView("unblock", cid), ephemeral=True,
        )

    @discord.ui.button(label="CLAIM",    emoji="👑", style=discord.ButtonStyle.success,    custom_id="tempvc:claim",    row=2)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user

        if not member.voice or not member.voice.channel:
            return await interaction.response.send_message(
                "❌ You must be **in** a voice channel to claim it!", ephemeral=True
            )

        channel = member.voice.channel
        if not db.exists(channel.id):
            return await interaction.response.send_message(
                "❌ You can only claim **temporary** voice channels!", ephemeral=True
            )

        ch_data = db.get(channel.id)
        if ch_data.owner_id == member.id:
            return await interaction.response.send_message(
                "❌ You already own this channel!", ephemeral=True
            )

        owner_still_present = any(m.id == ch_data.owner_id for m in channel.members)
        if owner_still_present:
            return await interaction.response.send_message(
                "❌ The owner is still in the channel. You can only claim an **ownerless** VC.",
                ephemeral=True,
            )

        old_owner = interaction.guild.get_member(ch_data.owner_id)
        if old_owner:
            await revoke_owner_perms(channel, old_owner)

        ch_data.owner_id = member.id
        await grant_owner_perms(channel, member)
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "👑 Channel Claimed",
            f"{member.mention} has claimed ownership of voice channel {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_claim', '👑')} You've successfully claimed **{channel.name}**!", ephemeral=True
        )

    @discord.ui.button(label="TRANSFER", emoji="🔄", style=discord.ButtonStyle.secondary,  custom_id="tempvc:transfer", row=2)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_transfer', '🔄')} **Transfer Ownership** — Hand control of your channel to someone in the VC.",
            view=UserActionView("transfer", cid), ephemeral=True,
        )

    @discord.ui.button(label="DELETE",   emoji="🗑️", style=discord.ButtonStyle.danger,     custom_id="tempvc:delete",   row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)

        extras = []
        if ch_data.waiting_room_id: extras.append("waiting room")
        if ch_data.chat_channel_id: extras.append("text chat")
        extra_note = f"\nThis will also delete the {' and '.join(extras)}." if extras else ""

        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_delete', '🗑️')} Are you sure you want to delete **{ch_data.name}**?{extra_note}",
            view=ConfirmDeleteView(cid, ch_data),
            ephemeral=True,
        )

def build_shared_embed(guild: discord.Guild | None = None) -> discord.Embed:
    embed = build_interface_embed(guild)
    embed.set_footer(text="made with <3 by whiskey.")
    return embed

class TempVCSharedView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    def customize_for_client(self, client: discord.Client) -> None:
        fallbacks = {
            "name": ("tempvc_ico_name", "🏷️"),
            "limit": ("tempvc_ico_limit", "👥"),
            "privacy": ("tempvc_ico_privacy", "🛡️"),
            "waiting": ("tempvc_ico_waiting", "⏳"),
            "chat": ("tempvc_ico_chat", "💬"),
            "trust": ("tempvc_ico_trust", "✅"),
            "untrust": ("tempvc_ico_untrust", "❌"),
            "invite": ("tempvc_ico_invite", "📨"),
            "kick": ("tempvc_ico_kick", "👢"),
            "region": ("tempvc_ico_region", "🌐"),
            "block": ("tempvc_ico_block", "🚫"),
            "unblock": ("tempvc_ico_unblock", "✔️"),
            "claim": ("tempvc_ico_claim", "👑"),
            "transfer": ("tempvc_ico_transfer", "🔄"),
            "delete": ("tempvc_ico_delete", "🗑️"),
        }
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id:
                parts = item.custom_id.split(":")
                if len(parts) == 2:
                    action = parts[1]
                    if action in fallbacks:
                        emoji_name, fallback_emoji = fallbacks[action]
                        item.emoji = get_button_emoji(client, emoji_name, fallback_emoji)
                        item.label = None


    @discord.ui.button(label="NAME",         emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:name",    row=0)
    async def btn_name(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_modal(NameModal(cid))

    @discord.ui.button(label="LIMIT",        emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:limit",   row=0)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_modal(LimitModal(cid))

    @discord.ui.button(label="PRIVACY",      emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:privacy", row=0)
    async def btn_privacy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(
            "🛡️ **Channel Privacy** — Choose how visible and accessible your channel is.",
            view=PrivacySelectView(cid), ephemeral=True,
        )

    @discord.ui.button(label="WAITING ROOM", emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:waiting", row=0)
    async def btn_waiting(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        if ch_data.waiting_room_id:
            wr = interaction.guild.get_channel(ch_data.waiting_room_id)
            if wr:
                try:
                    await wr.delete(reason="TempVC: Owner disabled waiting room")
                except discord.HTTPException:
                    pass
            ch_data.waiting_room_id = None
            status = "⏳ Waiting room **removed**."
        else:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=False),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
                interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
            }
            try:
                wr = await interaction.guild.create_voice_channel(
                    name="⏳ Waiting Room", category=channel.category,
                    overwrites=overwrites, reason="TempVC: Owner enabled waiting room",
                )
                ch_data.waiting_room_id = wr.id
                status = f"⏳ Waiting room created: {wr.mention}"
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Couldn't create waiting room — check bot permissions!", ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        action_str = f"created waiting room: {wr.mention}" if ch_data.waiting_room_id else "removed waiting room"
        await log_to_admin_channel(
            interaction.guild,
            "⏳ Waiting Room Toggled",
            f"Voice channel owner {interaction.user.mention} {action_str} for {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="CHAT",         emoji="💬", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:chat",    row=0)
    async def btn_chat(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        if ch_data.chat_channel_id:
            cc = interaction.guild.get_channel(ch_data.chat_channel_id)
            if cc:
                try:
                    await cc.delete(reason="TempVC: Owner disabled chat")
                except discord.HTTPException:
                    pass
            ch_data.chat_channel_id = None
            status = "💬 Text chat **removed**."
        else:
            safe_name = (channel.name.lower().replace("🎙️", "").replace(" ", "-").replace("'", "").strip("-") or "vc-chat")
            chat_perms = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=not ch_data.is_locked, send_messages=not ch_data.is_locked, read_message_history=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
            }
            try:
                cc = await interaction.guild.create_text_channel(name=f"💬-{safe_name}", category=channel.category, overwrites=chat_perms, reason="TempVC: Owner enabled chat")
                ch_data.chat_channel_id = cc.id
                status = f"💬 Text chat created: {cc.mention}"
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Couldn't create chat channel — check bot permissions!", ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        action_str = f"created text chat: {cc.mention}" if ch_data.chat_channel_id else "removed text chat"
        await log_to_admin_channel(
            interaction.guild,
            "💬 Chat Channel Toggled",
            f"Voice channel owner {interaction.user.mention} {action_str} for {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="TRUST",   emoji="✅", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:trust",   row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_trust', '✅')} **Trust a User**", view=UserActionView("trust", cid), ephemeral=True)

    @discord.ui.button(label="UNTRUST", emoji="❎", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:untrust", row=1)
    async def btn_untrust(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_untrust', '❎')} **Untrust a User**", view=UserActionView("untrust", cid), ephemeral=True)

    @discord.ui.button(label="INVITE",  emoji="📨", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:invite",  row=1)
    async def btn_invite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_invite', '📨')} **Invite a User**", view=UserActionView("invite", cid), ephemeral=True)

    @discord.ui.button(label="KICK",    emoji="👢", style=discord.ButtonStyle.danger,    custom_id="tempvcshared:kick",    row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        vc_members = [m for m in channel.members if m.id != interaction.user.id and not m.bot]
        if not vc_members:
            return await interaction.response.send_message("❌ Nobody else in your channel to kick!", ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_kick', '👢')} **Kick a User**", view=UserActionView("kick", cid), ephemeral=True)

    @discord.ui.button(label="REGION",  emoji="🌐", style=discord.ButtonStyle.secondary, custom_id="tempvcshared:region",  row=1)
    async def btn_region(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_region', '🌐')} **Change Voice Region**", view=RegionSelectView(cid), ephemeral=True)

    @discord.ui.button(label="BLOCK",    emoji="🚫", style=discord.ButtonStyle.danger,     custom_id="tempvcshared:block",    row=2)
    async def btn_block(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_block', '🚫')} **Block a User**", view=UserActionView("block", cid), ephemeral=True)

    @discord.ui.button(label="UNBLOCK",  emoji="✔️", style=discord.ButtonStyle.secondary,  custom_id="tempvcshared:unblock",  row=2)
    async def btn_unblock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_unblock', '✔️')} **Unblock a User**", view=UserActionView("unblock", cid), ephemeral=True)

    @discord.ui.button(label="CLAIM",    emoji="👑", style=discord.ButtonStyle.success,    custom_id="tempvcshared:claim",    row=2)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user
        if not member.voice or not member.voice.channel:
            return await interaction.response.send_message("❌ You must be **in** a voice channel to claim it!", ephemeral=True)
        channel = member.voice.channel
        if not db.exists(channel.id):
            return await interaction.response.send_message("❌ You can only claim **temporary** voice channels!", ephemeral=True)
        ch_data = db.get(channel.id)
        if ch_data.owner_id == member.id:
            return await interaction.response.send_message("❌ You already own this channel!", ephemeral=True)
        if any(m.id == ch_data.owner_id for m in channel.members):
            return await interaction.response.send_message("❌ The owner is still in the channel!", ephemeral=True)
        old_owner = interaction.guild.get_member(ch_data.owner_id)
        if old_owner:
            await revoke_owner_perms(channel, old_owner)
        ch_data.owner_id = member.id
        await grant_owner_perms(channel, member)
        await refresh_panel(interaction.client, interaction.guild, ch_data, channel)
        from utils.log_utils import log_to_admin_channel
        await log_to_admin_channel(
            interaction.guild,
            "👑 Channel Claimed",
            f"{member.mention} has claimed ownership of voice channel {channel.mention}.",
            color=0x3498DB
        )
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_claim', '👑')} You've claimed **{channel.name}**!", ephemeral=True)

    @discord.ui.button(label="TRANSFER", emoji="🔄", style=discord.ButtonStyle.secondary,  custom_id="tempvcshared:transfer", row=2)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, ch, data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"{get_emoji(interaction.client, 'tempvc_ico_transfer', '🔄')} **Transfer Ownership**", view=UserActionView("transfer", cid), ephemeral=True)

    @discord.ui.button(label="DELETE",   emoji="🗑️", style=discord.ButtonStyle.danger,     custom_id="tempvcshared:delete",   row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cid, channel, ch_data, err = await _shared_owner_check(interaction)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        extras = []
        if ch_data.waiting_room_id: extras.append("waiting room")
        if ch_data.chat_channel_id: extras.append("text chat")
        extra_note = f"\nThis will also delete the {' and '.join(extras)}." if extras else ""
        await interaction.response.send_message(
            f"{get_emoji(interaction.client, 'tempvc_ico_delete', '🗑️')} Are you sure you want to delete **{ch_data.name}**?{extra_note}",
            view=ConfirmDeleteView(cid, ch_data), ephemeral=True,
        )

class PanelCog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        bot.add_view(TempVCControlView())
        bot.add_view(TempVCSharedView())

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanelCog(bot))
