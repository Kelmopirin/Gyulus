import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

import discord
from discord.ext import commands

from storage import Storage

EG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -stream_loop -1",
    "options": "-vn",
}
ALIAS_PATTERN = re.compile(r"[\w\- ]{1,64}")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.storage = Storage()
        # 256 MB RAM mellett egyszerre csak egy letöltés/konvertálás futhat.
        self.download_lock = asyncio.Lock()

    @commands.hybrid_command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        await ctx.defer()
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("Előbb csatlakozz egy hangcsatornához!")
            return

        query = query.strip().lower()
        try:
            tracks = await self.storage.list_tracks()
        except Exception as error:
            print(f"Tárhely hiba: {error!r}")
            await ctx.send("Nem sikerült elérni a zenetárat.")
            return

        track = next((name for name in tracks if query and query in name.lower()), None)
        if track is None:
            await ctx.send(f"Nincs ilyen szám a zenetárban: `{query}`")
            return
        track_url = await self.storage.presigned_url(track)

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
            discord.FFmpegPCMAudio(track_url, **EG_OPTIONS),
            after=playback_error,
        )
        await ctx.send(f"Lejátszás: **{track}**")

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
        if (
            not separator
            or not url.lower().startswith(("http://", "https://"))
            or not ALIAS_PATTERN.fullmatch(alias)
        ):
            await ctx.send("Használat: `/download <URL> <név>` (a név betű, szám, szóköz, `-` vagy `_`).")
            return

        if self.download_lock.locked():
            await ctx.send("Már folyik egy letöltés, próbáld újra később.")
            return

        async with self.download_lock:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        [
                            "yt-dlp",
                            "-x",
                            "--audio-format",
                            "mp3",
                            "--no-playlist",
                            "-o",
                            str(temp_path / "track.%(ext)s"),
                            "--",
                            url,
                        ],
                        check=True,
                    )
                    await self.storage.upload(temp_path / "track.mp3", alias.lower())
                except FileNotFoundError:
                    await ctx.send("A letöltéshez telepíteni kell az `yt-dlp` programot.")
                    return
                except subprocess.CalledProcessError:
                    await ctx.send("A letöltés nem sikerült.")
                    return
                except Exception as error:
                    print(f"Feltöltési hiba: {error!r}")
                    await ctx.send("A feltöltés a zenetárba nem sikerült.")
                    return

        await ctx.send(f"Letöltve: **{alias}**")

    @commands.hybrid_command(name="takarodj")
    async def takarodj(self, ctx: commands.Context) -> None:
        await self.leave.callback(self, ctx)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
