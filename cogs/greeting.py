import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from discord.ext import commands, tasks

TIMEZONE = ZoneInfo("Europe/Budapest")
GREETING_DAY = 17
GREETING_TIME = time(19, 50, tzinfo=TIMEZONE)


class Greeting(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.wedding_greeting.start()

    @tasks.loop(time=GREETING_TIME)
    async def wedding_greeting(self) -> None:
        if datetime.now(TIMEZONE).day != GREETING_DAY:
            return

        channel_id = os.getenv("GREETING_CHANNEL_ID")
        user_id = os.getenv("NANDRIS_USER_ID")
        if not channel_id or not user_id:
            print("GREETING_CHANNEL_ID vagy NANDRIS_USER_ID hiányzik a .env fájlból.")
            return

        channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(
            int(channel_id)
        )
        await channel.send(
            f"Jó reggelt, <@{int(user_id)}>! 🌞 Gratulálunk az esküvődhöz! 💍🎉"
        )

    @wedding_greeting.before_loop
    async def before_wedding_greeting(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Greeting(bot))
