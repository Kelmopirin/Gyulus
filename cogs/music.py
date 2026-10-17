from pathlib import Path
import subprocess

import discord
from discord.ext import commands

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIRECTORY = PROJECT_ROOT / "music"

EG_OPTIONS = {
    "before_options": "-stream_loop -1",
    "options": "-vn",
}


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        await ctx.defer()
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("Előbb csatlakozz egy hangcsatornához!")
            return

        query = query.strip().lower()
        music_file = next(
            (
                path
                for path in sorted(MUSIC_DIRECTORY.glob("*.mp3"), key=lambda item: item.name.lower())
                if query and query in path.stem.lower()
            ),
            None,
        )
        if music_file is None:
            await ctx.send(f"Nincs ilyen szám a music mappában: `{query}`")
            return

        voice_channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            voice_client = await voice_channel.connect()
        else:
            voice_client = ctx.voice_client
            if voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)

        if voice_client.is_playing():
            voice_client.stop()

        def playback_error(error: Exception | None) -> None:
            if error:
                print(f"Lejátszási hiba: {error!r}")

        voice_client.play(
            discord.FFmpegPCMAudio(str(music_file), **EG_OPTIONS),
            after=playback_error,
        )
        await ctx.send(f"Lejátszás: **{music_file.stem}**")

    @commands.hybrid_command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Leállítva a lejátszást.")
        else:
            await ctx.send("Nincs lejátszás folyamatban.")

    @commands.hybrid_command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Szüneteltetve a lejátszást.")
        else:
            await ctx.send("Nincs lejátszás folyamatban.")

    @commands.hybrid_command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Folytatva a lejátszást.")
        else:
            await ctx.send("Nincs szüneteltetett lejátszás.")

    @commands.hybrid_command(name="set-volume")
    async def set_volume(self, ctx: commands.Context, volume: float) -> None:
        if ctx.voice_client is not None and ctx.voice_client.is_playing():
            ctx.voice_client.source.volume = max(0.0, min(volume, 1.0))
            await ctx.send(f"Hangerő beállítva: {ctx.voice_client.source.volume:.1f}")
        else:
            await ctx.send("Nincs lejátszás folyamatban.")

    @commands.hybrid_command(name="leave")
    async def leave(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect()
            await ctx.send("Kilépve a hangcsatornából.")
        else:
            await ctx.send("Nem vagyok hangcsatornán.")

    @commands.hybrid_command(name="p")
    async def p(self, ctx: commands.Context, *, query: str) -> None:
        await self.play.callback(self, ctx, query=query)

    @commands.hybrid_command(name="download")
    async def download(self, ctx: commands.Context, *, query: str) -> None:
        await ctx.defer()
        url, separator, alias = query.strip().partition(" ")
        alias = alias.strip()
        if not separator or not alias or Path(alias).name != alias or alias in {".", ".."}:
            await ctx.send("Használat: `/download <URL> <név>`")
            return

        MUSIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    "-x",
                    "--audio-format",
                    "mp3",
                    url,
                    "-o",
                    str(MUSIC_DIRECTORY / f"{alias}.%(ext)s"),
                ],
                check=True,
            )
        except FileNotFoundError:
            await ctx.send("A letöltéshez telepíteni kell az `yt-dlp` programot.")
            return
        except subprocess.CalledProcessError:
            await ctx.send("A letöltés nem sikerült.")
            return

        await ctx.send(f"Letöltve: **{alias}**")

    @commands.hybrid_command(name="takarodj")
    async def takarodj(self, ctx: commands.Context) -> None:
        await self.leave.callback(self, ctx)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
