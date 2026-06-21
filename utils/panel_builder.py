
from __future__ import annotations
import discord
from utils.database import TempChannel

def get_emoji(guild: discord.Guild | None, name: str, fallback: str) -> str:
    if not guild:
        return fallback
    prefixes = ["tempvc_ico_", "tempvc_icon_", "tempvc_btn_", "tempvc_", "vvc_ico_", "vvc_icon_", "vvc_btn_", "vvc_", ""]
    for prefix in prefixes:
        clean_name = name.replace("tempvc_ico_", "").replace("tempvc_icon_", "").replace("tempvc_btn_", "").replace("tempvc_", "").replace("vvc_ico_", "").replace("vvc_icon_", "").replace("vvc_btn_", "").replace("vvc_", "")
        emoji = discord.utils.get(guild.emojis, name=f"{prefix}{clean_name}")
        if emoji:
            return str(emoji)
    emoji = discord.utils.get(guild.emojis, name=name)
    if emoji:
        return str(emoji)
    return fallback

def get_button_emoji(guild: discord.Guild | None, name: str, fallback: str):
    if not guild:
        return fallback
    prefixes = ["tempvc_ico_", "tempvc_icon_", "tempvc_btn_", "tempvc_", "vvc_ico_", "vvc_icon_", "vvc_btn_", "vvc_", ""]
    for prefix in prefixes:
        clean_name = name.replace("tempvc_ico_", "").replace("tempvc_icon_", "").replace("tempvc_btn_", "").replace("tempvc_", "").replace("vvc_ico_", "").replace("vvc_icon_", "").replace("vvc_btn_", "").replace("vvc_", "")
        emoji = discord.utils.get(guild.emojis, name=f"{prefix}{clean_name}")
        if emoji:
            return emoji
    emoji = discord.utils.get(guild.emojis, name=name)
    if emoji:
        return emoji
    return fallback

def build_interface_embed(guild: discord.Guild | None) -> discord.Embed:
    desc = (
        "Welcome to your personal voice channel control panel!\n"
        "Use the buttons below to customize and manage your temporary voice channel."
    )
    embed = discord.Embed(
        title="Whiskey MowMow",
        description=desc,
        color=0xfd3c65,
    )
    embed.set_image(url="attachment://interface.png")
    embed.set_footer(text="made with ❤️ by whiskey")
    return embed


def build_embed(
    channel: discord.VoiceChannel,
    data: TempChannel,
) -> discord.Embed:
    return build_interface_embed(channel.guild)

