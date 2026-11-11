import discord
from discord.ext import commands
from openai import OpenAI
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="summary")
    async def summary(
        self, ctx: commands.Context, since: str
    ) -> None:
        """
        AI összefoglalót készít az üzenetekből egy adott időpontól.
        
        Args:
            since: Időpont formátum (pl. "17:05" vagy "14:30")
        
        Usage: /summary 17:05
        """
        await ctx.defer()  # Defer, mert hosszabb lehet a feldolgozás
        
        # Parse időpont
        try:
            time_parts = since.split(":")
            if len(time_parts) != 2:
                await ctx.followup.send(
                    "❌ Hibás időpont formátum! Használat: `/summary 17:05`"
                )
                return
            
            hour, minute = int(time_parts[0]), int(time_parts[1])
            
            # Szerzünk egy datetime objektumot az aktuális napból
            now = datetime.now()
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # Ha az idő a jövőben van, az előző napra vonatkozik
            if target_time > now:
                target_time -= timedelta(days=1)
        
        except (ValueError, IndexError):
            await ctx.followup.send(
                "❌ Hibás időpont formátum! Használat: `/summary 17:05`"
            )
            return

        # Üzenetek gyűjtése
        messages_text = []
        async for message in ctx.channel.history(
            limit=None, after=target_time
        ):
            # Bot saját üzeneteit nem vesszük figyelembe
            if message.author.bot:
                continue
            
            # Formázott üzenet hozzáadása
            messages_text.append(
                f"[{message.created_at.strftime('%H:%M:%S')}] {message.author.name}: {message.content}"
            )

        if not messages_text:
            await ctx.followup.send(
                f"❌ Nem találtam üzenetet {since} óta a csatornán."
            )
            return

        # Üzenetek összekapcsolása
        full_conversation = "\n".join(messages_text)

        # OpenAI API hívás
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "Te egy Discord csatorna üzeneteinek összefoglalója vagy. "
                                   "Írj egy rövid, érdekes magyar nyelvű összefoglalót az alábbi beszélgetésről. "
                                   "Emeld ki a legfontosabb pontokat és témákat.",
                    },
                    {
                        "role": "user",
                        "content": f"Foglald össze ezt a beszélgetést:\n\n{full_conversation}",
                    },
                ],
                temperature=0.7,
                max_tokens=500,
            )

            summary_text = response.choices[0].message.content

            # Eredmény küldése
            embed = discord.Embed(
                title="📝 Csatorna Összefoglaló",
                description=summary_text,
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Összefoglalva: {since} óta")
            embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url)

            await ctx.followup.send(embed=embed)

        except Exception as e:
            await ctx.followup.send(
                f"❌ Hiba az OpenAI API meghívásakor: {str(e)}"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
