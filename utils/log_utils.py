import discord
from utils.database import db

async def log_to_admin_channel(
    guild: discord.Guild,
    title: str,
    description: str,
    color: int = 0x5865F2,
    fields: list[dict] | None = None
) -> None:
    config = db.get_config(guild.id)
    if not config or not config.log_channel_id:
        return

    channel = guild.get_channel(config.log_channel_id)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="made with ❤️ by whiskey")

    if fields:
        for f in fields:
            embed.add_field(
                name=f.get("name", ""),
                value=f.get("value", ""),
                inline=f.get("inline", True)
            )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
