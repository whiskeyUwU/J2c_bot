
import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.voice_states    = True
intents.members         = True
intents.guilds          = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.setup_cog",
    "cogs.voice_cog",
    "cogs.panel_cog",
]

@bot.event
async def on_ready() -> None:
    print(f"✅  Logged in as {bot.user}  (ID: {bot.user.id})")
    print("─" * 40)

    guild_id = os.getenv("GUILD_ID")
    try:
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"⚡  Synced {len(synced)} command(s) to guild {guild_id} (instant)")
        else:
            synced = await bot.tree.sync()
            print(f"🌐  Synced {len(synced)} command(s) globally (may take up to 1 hour)")
    except Exception as exc:
        print(f"❌  Failed to sync commands: {exc}")

    print("─" * 40)
    print("🎙️  TempVC Bot is ready!")

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    print(f"📥  Joined guild: {guild.name} ({guild.id})")

async def main() -> None:
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅  Loaded {cog}")
            except Exception as exc:
                print(f"❌  Failed to load {cog}: {exc}")

        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "BOT_TOKEN is not set. Copy .env.example → .env and fill in your token."
            )
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
