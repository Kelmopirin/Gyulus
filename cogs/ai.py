import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def summary_limits(elapsed: timedelta) -> tuple[int, int]:
    hours = elapsed.total_seconds() / 3600
    if hours < 1:
        return 600, 500
    if hours < 6:
        return 1200, 900
    if hours < 12:
        return 2400, 1700
    return 3800, 2600


def parse_summary_time(value: str, reference: datetime) -> datetime:
    match = re.fullmatch(r"(\d{1,2})(?:[:.](\d{1,2}))?", value)
    if match is None:
        raise ValueError("Invalid time format")
    return reference.replace(
        hour=int(match.group(1)), minute=int(match.group(2) or 0),
        second=0, microsecond=0,
    )


def parse_summary_date(value: str) -> datetime:
    match = re.fullmatch(r"(\d{4})([-.])(\d{2})\2(\d{2})", value)
    if match is None:
        raise ValueError("Invalid date format")
    return datetime(int(match.group(1)), int(match.group(3)), int(match.group(4)))


async def summary_suggestions(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    now = datetime.now()
    values = []
    for days in range(7):
        day = now - timedelta(days=days)
        values.extend((day.strftime("%Y-%m-%d"), day.strftime("%Y.%m.%d")))
    values.extend(f"{hour:02d}:00" for hour in range(24))
    return [
        app_commands.Choice(name=value, value=value)
        for value in values if value.startswith(current.strip())
    ][:25]


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="summary")
    @app_commands.describe(
        since="Kezdő időpont vagy dátum, például 17:00 vagy 2026-11-10",
        end="Opcionális záró időpont vagy dátum",
    )
    @app_commands.autocomplete(since=summary_suggestions, end=summary_suggestions)
    async def summary(
        self, ctx: commands.Context, since: str, end: str | None = None
    ) -> None:
        """
        AI összefoglalót készít az üzenetekből egy adott időpontól.
        
        Args:
            since: Kezdő időpont vagy dátum (pl. "17:05" vagy "2026-11-11")
            end: Opcionális záró időpont vagy dátum, a kezdettel egyező típusban
        
        Usage: /summary 17:05 19:00
        """
        await ctx.defer()  # Defer, mert hosszabb lehet a feldolgozás
        
        try:
            now = datetime.now()
            is_date = re.match(r"\d{4}[-.]", since) is not None
            if is_date:
                target_time = parse_summary_date(since)
                last_day = parse_summary_date(end) if end is not None else target_time
                if last_day < target_time:
                    raise ValueError("End date is before start date")
                if last_day.date() > now.date():
                    raise ValueError("Date is in the future")
                end_time = last_day + timedelta(days=1)
            else:
                end_time = parse_summary_time(end, now) if end is not None else now
                if end_time > now:
                    end_time -= timedelta(days=1)
                target_time = parse_summary_time(since, end_time)
                if target_time > end_time or (end is not None and target_time == end_time):
                    target_time -= timedelta(days=1)

        except (ValueError, OverflowError):
            await ctx.send(
                "❌ Hibás időpont vagy dátum! Használat: `/summary 17:05 19:00` "
                "vagy `/summary 2026-11-10 2026-11-11`. "
                "A kezdő és záró érték legyen azonos típusú; a dátumok nem lehetnek jövőbeliek."
            )
            return

        # Üzenetek gyűjtése
        messages_text = []
        history_options = {"limit": None, "after": target_time}
        if end is not None or is_date:
            history_options = {
                "limit": None,
                "after": discord.Object(id=discord.utils.time_snowflake(target_time) - 1),
                "before": end_time,
            }
        async for message in ctx.channel.history(**history_options):
            # Bot saját üzeneteit nem vesszük figyelembe
            if message.author.bot:
                continue
            
            # Formázott üzenet hozzáadása
            timestamp = message.created_at
            if is_date:
                timestamp = timestamp.astimezone()
            time_format = "%Y-%m-%d %H:%M:%S" if is_date else "%H:%M:%S"
            messages_text.append(f"[{timestamp.strftime(time_format)}] {message.author.name}: {message.content}")

        if not messages_text:
            period = f"{since} és {end} között" if end is not None else (
                f"{since} napján" if is_date else f"{since} óta"
            )
            await ctx.send(f"❌ Nem találtam üzenetet {period} a csatornán.")
            return

        # Üzenetek összekapcsolása
        full_conversation = "\n".join(reversed(messages_text) if is_date else messages_text)
        elapsed = min(end_time, now) - target_time
        max_characters, max_tokens = summary_limits(elapsed)

        # OpenAI API hívás
        try:
            response = client.chat.completions.create(
                model="gpt-6-luna",
                messages=[
                    {
                        "role": "system",
                        "content": "Te egy Discord csatorna üzeneteinek összefoglalója vagy. "
                                   "Írj magyar nyelvű összefoglalót az alábbi beszélgetésről. "
                                   "Emeld ki a legfontosabb pontokat és témákat. "
                                   "A részletességet igazítsd az időtartamhoz és a beszélgetés tartalmához; "
                                   "ne találj ki részleteket, ha kevés az információ. "
                                   f"Az összefoglaló legfeljebb {max_characters} karakter legyen.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Eltelt idő: {elapsed.total_seconds() / 3600:.1f} óra.\n"
                            f"Foglald össze ezt a beszélgetést:\n\n{full_conversation}"
                        ),
                    },
                ],
                reasoning_effort="none",
                temperature=0.7,
                max_completion_tokens=max_tokens,
            )

            summary_text = response.choices[0].message.content
            if not summary_text:
                await ctx.send("❌ Az OpenAI nem adott vissza szöveges összefoglalót.")
                return

            if len(summary_text) > 4096 or response.choices[0].finish_reason == "length":
                suffix = "\n\n*(Az összefoglaló a hosszkorlát miatt rövidítve.)*"
                summary_text = summary_text[:4096 - len(suffix)] + suffix

            # Eredmény küldése
            embed = discord.Embed(
                title="📝 Csatorna Összefoglaló",
                description=summary_text,
                color=discord.Color.blue(),
            )
            period = f"{since}–{end}" if end is not None else (
                since if is_date else f"{since} óta"
            )
            embed.set_footer(text=f"Összefoglalva: {period}")
            embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                f"❌ Hiba az OpenAI API meghívásakor: {str(e)}"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
