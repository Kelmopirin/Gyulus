import random
import re

from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="hello")
    async def hello(self, ctx: commands.Context) -> None:
        await ctx.send("Halika!!! De fáj Trianon")

    @commands.hybrid_command(name="r")
    async def roll_dice(self, ctx: commands.Context, *, query: str) -> None:
        match = re.fullmatch(r"\s*(\d+)d(\d+)\s*([+-])?\s*(\d+)?\s*", query.lower())
        if match is None or (match.group(3) is None) != (match.group(4) is None):
            await ctx.send("Hibás dobás. Használat: `1d20`, `2d4 + 3` vagy `3d6 - 2`.")
            return

        num, die = map(int, match.group(1, 2))
        if die < 1:
            await ctx.send("A kocka oldalainak száma legalább 1 legyen.")
            return

        rolls = [random.randint(1, die) for _ in range(num)]
        modifier = int(match.group(4) or 0)
        if match.group(3) == "-":
            modifier *= -1
        total = sum(rolls) + modifier

        result = f"{num}d{die} ({', '.join(map(str, rolls))})"
        if match.group(3) is not None:
            result += f" {match.group(3)} {match.group(4)}"

        await ctx.send(
            f"{ctx.author.mention} 🎲\n"
            f"**Result:** {result}\n"
            f"**Total:** {total}"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
