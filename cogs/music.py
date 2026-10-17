import asyncio
import hashlib
import re
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from storage import TEMP_PREFIX, Storage, job_key, result_key

EG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -stream_loop -1",
    "options": "-vn",
}
ALIAS_PATTERN = re.compile(r"[\w\- ]{1,64}")
TEMP_MAX_AGE = timedelta(hours=1)
JOB_TIMEOUT = 180
JOB_POLL_INTERVAL = 2


class DownloadError(Exception):
    pass


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.storage = Storage()

    async def cog_load(self) -> None:
        self.cleanup_temp.start()

    async def cog_unload(self) -> None:
        self.cleanup_temp.cancel()

    @tasks.loop(minutes=10)
    async def cleanup_temp(self) -> None:
        try:
            removed = await self.storage.cleanup_temp(TEMP_MAX_AGE)
        except Exception as error:
            print(f"Temp takarítási hiba: {error!r}")
            return
        if removed:
            print(f"Temp takarítás: {removed} fájl törölve.")

    async def _request_download(self, url: str, key: str) -> str | None:
        """Letöltési kérést ad a workernek, és megvárja az eredményt. Visszaadja a címet, ha elérhető."""
        job_id = hashlib.sha1(f"{key}|{url}".encode()).hexdigest()[:16]
        try:
            await self.storage.delete(result_key(job_id))
            await self.storage.put_json(job_key(job_id), {"url": url, "key": key})

            loop = asyncio.get_running_loop()
            deadline = loop.time() + JOB_TIMEOUT
            while loop.time() < deadline:
                result = await self.storage.get_json(result_key(job_id))
                if result is not None:
                    await self.storage.delete(result_key(job_id))
                    if result.get("ok"):
                        return result.get("title")
                    raise DownloadError(result.get("error") or "A letöltés nem sikerült.")
                await asyncio.sleep(JOB_POLL_INTERVAL)

            await self.storage.delete(job_key(job_id))
        except DownloadError:
            raise
        except Exception as error:
            print(f"Tárhely hiba: {error!r}")
            raise DownloadError("Nem sikerült elérni a zenetárat.")
        raise DownloadError("A letöltő szerver nem válaszolt időben, próbáld újra később.")

    async def _prepare_temp_track(self, url: str) -> tuple[str, str]:
        """Ideiglenes számot készít a linkből. Visszaadja a tárhelykulcsot és a megjelenített nevet."""
        key = f"{TEMP_PREFIX}{hashlib.sha1(url.encode()).hexdigest()[:16]}"
        try:
            if await self.storage.exists(key):
                return key, url
        except Exception as error:
            print(f"Tárhely hiba: {error!r}")
            raise DownloadError("Nem sikerült elérni a zenetárat.")

        title = await self._request_download(url, key)
        return key, title or url

    @commands.hybrid_command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        await ctx.defer()
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("Előbb csatlakozz egy hangcsatornához!")
            return

        query = query.strip()
        if is_url(query):
            await ctx.send("Letöltés folyamatban, egy pillanat...")
            try:
                track, display_name = await self._prepare_temp_track(query)
            except DownloadError as error:
                await ctx.send(str(error))
                return
        else:
            query = query.lower()
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
            display_name = track
        track_url = await self.storage.presigned_url(track)

        voice_channel = ctx.author.voice.channel
        permissions = voice_channel.permissions_for(ctx.guild.me)
        if not (permissions.view_channel and permissions.connect and permissions.speak):
            await ctx.send("A botnak nincs **Csatlakozás** és **Beszéd** jogosultsága ezen a hangcsatornán.")
            return

        voice_client = ctx.voice_client
        if voice_client is not None and not voice_client.is_connected():
            await voice_client.disconnect(force=True)
            voice_client = None

        try:
            if voice_client is None:
                voice_client = await voice_channel.connect(timeout=30)
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except (asyncio.TimeoutError, discord.ClientException) as error:
            print(f"Hangcsatlakozási hiba: {error!r}")
            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect(force=True)
            await ctx.send("Nem sikerült csatlakozni a hangcsatornához, próbáld újra később.")
            return

        if voice_client.is_playing():
            voice_client.stop()

        def playback_error(error: Exception | None) -> None:
            if error:
                print(f"Lejátszási hiba: {error!r}")

        voice_client.play(
            discord.FFmpegPCMAudio(track_url, **EG_OPTIONS),
            after=playback_error,
        )
        await ctx.send(f"Lejátszás: **{display_name}**")

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
        if not separator or not is_url(url) or not ALIAS_PATTERN.fullmatch(alias):
            await ctx.send("Használat: `/download <URL> <név>` (a név betű, szám, szóköz, `-` vagy `_`).")
            return

        try:
            await self._request_download(url, alias.lower())
        except DownloadError as error:
            await ctx.send(str(error))
            return

        await ctx.send(f"Letöltve: **{alias}**")

    @commands.hybrid_command(name="takarodj")
    async def takarodj(self, ctx: commands.Context) -> None:
        await self.leave.callback(self, ctx)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
