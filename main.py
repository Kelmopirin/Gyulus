import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()


class GyulusBot(commands.Bot):
    async def setup_hook(self) -> None:
        for extension in ("cogs.general", "cogs.music", "cogs.greeting"):
            await self.load_extension(extension)
        await self.tree.sync()


intents = discord.Intents.default()
intents.message_content = True

bot = GyulusBot(command_prefix="/", intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}")


bot.run(os.getenv("DISCORD_TOKEN"))
