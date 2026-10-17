import asyncio
import hashlib
import random
import re
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from storage import TEMP_PREFIX, Storage, job_key, result_key

EG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
EG_LOOP_OPTION = "-stream_loop -1"
ALIAS_PATTERN = re.compile(r"[\w\- ]{1,64}")
TEMP_MAX_AGE = timedelta(hours=1)
JOB_TIMEOUT = 180
JOB_POLL_INTERVAL = 2


class DownloadError(Exception):
    pass


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


class GuildPlayer:
    """Egy szerver lejátszási állapota."""

    def __init__(self) -> None:
        self.loop = True
        self.volume = 1.0
        self.track: str | None = None
        self.token = 0
        self.text_channel: discord.abc.Messageable | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.storage = Storage()
        self.players: dict[int, GuildPlayer] = {}

    def player(self, guild_id: int) -> GuildPlayer:
        return self.players.setdefault(guild_id, GuildPlayer())

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

        query = " ".join(query.split())
        if not query:
            await ctx.send("Adj meg egy számot, linket vagy keresőszöveget.")
            return

        track = None
        display_name = query
        if not is_url(query):
            lowered = query.lower()
            try:
                tracks = await self.storage.list_tracks()
            except Exception as error:
                print(f"Tárhely hiba: {error!r}")
                await ctx.send("Nem sikerült elérni a zenetárat.")
                return
            track = next((name for name in tracks if lowered in name.lower()), None)
            if track is not None:
                display_name = track

        if track is None:
            # Link vagy a zenetárban nem található szöveg: az első YouTube-találatot töltjük le.
            source = query if is_url(query) else f"ytsearch1:{query[:200]}"
            await ctx.send(
                "Letöltés folyamatban, egy pillanat..."
                if is_url(query)
                else f"Nincs ilyen a zenetárban, keresés YouTube-on: `{query}`"
            )
            try:
                track, display_name = await self._prepare_temp_track(source)
            except DownloadError as error:
                await ctx.send(str(error))
                return
            if not is_url(query) and display_name == source:
                display_name = query

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

        await self._start_track(voice_client, ctx.channel, track, display_name)

    async def _start_track(
        self,
        voice_client: discord.VoiceClient,
        text_channel: discord.abc.Messageable,
        track: str,
        display_name: str,
    ) -> None:
        state = self.player(voice_client.guild.id)
        track_url = await self.storage.presigned_url(track)

        # A token érvényteleníti a korábbi lejátszás befejezési visszahívását (pl. leállításkor).
        state.token += 1
        token = state.token
        state.track = track
        state.text_channel = text_channel

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        def playback_finished(error: Exception | None) -> None:
            if error:
                print(f"Lejátszási hiba: {error!r}")
            asyncio.run_coroutine_threadsafe(
                self._on_playback_finished(voice_client, token), self.bot.loop
            )

        before_options = EG_BEFORE_OPTIONS + (f" {EG_LOOP_OPTION}" if state.loop else "")
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(track_url, before_options=before_options, options="-vn"),
            volume=state.volume,
        )
        voice_client.play(source, after=playback_finished)
        await text_channel.send(f"Lejátszás: **{display_name}**")

    async def _on_playback_finished(self, voice_client: discord.VoiceClient, token: int) -> None:
        state = self.player(voice_client.guild.id)
        if token != state.token or not voice_client.is_connected():
            return
        state.token += 1

        try:
            tracks = await self.storage.list_tracks()
            if state.loop and state.track is not None:
                next_track = state.track
            else:
                choices = [name for name in tracks if name != state.track] or tracks
                if not choices:
                    return
                next_track = random.choice(choices)
            await self._start_track(voice_client, state.text_channel, next_track, next_track)
        except Exception as error:
            print(f"Következő szám indítási hiba: {error!r}")

    @commands.hybrid_command(name="setloop")
    async def setloop(self, ctx: commands.Context, value: bool) -> None:
        """True: az aktuális szám ismétlődik. False: a szám végén véletlen szám indul a zenetárból."""
        self.player(ctx.guild.id).loop = value
        if value:
            await ctx.send("Ismétlés bekapcsolva: a szám újra és újra lejátszódik.")
        else:
            await ctx.send("Ismétlés kikapcsolva: a szám végén véletlen szám indul a zenetárból.")
        if ctx.voice_client is not None and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            await ctx.send("A beállítás a jelenlegi szám lejátszása után lép életbe.")

    @commands.hybrid_command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None and ctx.voice_client.is_playing():
            self.player(ctx.guild.id).token += 1
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
        """Hangerő 0.0 és 1.0 között."""
        state = self.player(ctx.guild.id)
        state.volume = max(0.0, min(volume, 1.0))
        source = ctx.voice_client.source if ctx.voice_client is not None else None
        if isinstance(source, discord.PCMVolumeTransformer):
            source.volume = state.volume
        await ctx.send(f"Hangerő beállítva: {state.volume:.1f}")

    @commands.hybrid_command(name="leave")
    async def leave(self, ctx: commands.Context) -> None:
        if ctx.voice_client is not None:
            self.player(ctx.guild.id).token += 1
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
