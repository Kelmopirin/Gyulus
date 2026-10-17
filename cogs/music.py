import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks

from storage import TEMP_PREFIX, Storage

EG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -stream_loop -1",
    "options": "-vn",
}
ALIAS_PATTERN = re.compile(r"[\w\- ]{1,64}")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP_MAX_AGE = timedelta(hours=1)
MAX_DOWNLOAD_SIZE = "100M"


class DownloadError(Exception):
    pass


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


def find_js_runtime() -> tuple[str, str] | None:
    # A pip-pel telepített futtatók gyakran olyan mappába kerülnek, ami nincs a PATH-on.
    search_path = os.pathsep.join(
        [
            os.environ.get("PATH", ""),
            str(Path.home() / ".local" / "bin"),
            str(Path(sys.executable).parent),
        ]
    )
    for runtime in ("deno", "node", "bun"):
        found = shutil.which(runtime, path=search_path)
        if found:
            return runtime, found
    return None


def cookies_args() -> list[str]:
    cookies = os.getenv("YTDLP_COOKIES_FILE")
    if not cookies:
        return []
    cookies_path = Path(cookies)
    if not cookies_path.is_absolute():
        cookies_path = PROJECT_ROOT / cookies_path
    return ["--cookies", str(cookies_path)] if cookies_path.is_file() else []


def ytdlp_attempts() -> list[tuple[str, list[str]]]:
    """A letöltési kísérletek sorrendben. Az első a legkevesebb memóriát használja."""
    # JS-futtató és süti nélkül a YouTube JS-t nem igénylő kliensei használhatók.
    attempts = [
        ("JS és süti nélkül", ["--no-js-runtimes"]),
        (
            "android_vr kliens",
            ["--no-js-runtimes", "--extractor-args", "youtube:player_client=android_vr"],
        ),
        (
            "tv + web_embedded kliens",
            ["--no-js-runtimes", "--extractor-args", "youtube:player_client=tv,web_embedded", *cookies_args()],
        ),
    ]
    runtime = find_js_runtime()
    if runtime:
        attempts.append(
            ("süti + " + runtime[0], ["--js-runtimes", f"{runtime[0]}:{runtime[1]}", *cookies_args()])
        )
    elif cookies_args():
        attempts.append(("süti", cookies_args()))
    return attempts


def ytdlp_environment() -> dict[str, str]:
    env = os.environ.copy()
    # A deno alapból sok memóriát foglalhat, 256 MB-on ilyenkor kilövi a rendszer (returncode -9).
    env.setdefault("DENO_V8_FLAGS", "--max-old-space-size=96")
    return env


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.storage = Storage()
        # 256 MB RAM mellett egyszerre csak egy letöltés/konvertálás futhat.
        self.download_lock = asyncio.Lock()

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

    async def _download_to_storage(self, url: str, name: str) -> str | None:
        """Letölti a linket mp3-ként, és feltölti a tárhelyre. Visszaadja a címet, ha elérhető."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            result = None
            for label, extra_args in ytdlp_attempts():
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        [
                            sys.executable,
                            "-m",
                            "yt_dlp",
                            *extra_args,
                            "-x",
                            "--audio-format",
                            "mp3",
                            "--no-playlist",
                            "--max-filesize",
                            MAX_DOWNLOAD_SIZE,
                            "--print",
                            "title",
                            "--no-simulate",
                            "-o",
                            str(temp_path / "track.%(ext)s"),
                            "--",
                            url,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        env=ytdlp_environment(),
                    )
                    break
                except subprocess.CalledProcessError as error:
                    print(f"yt-dlp hiba ({label}): {error.stderr[-1500:]}")
            if result is None:
                raise DownloadError("A letöltés nem sikerült.")

            track_file = temp_path / "track.mp3"
            if not track_file.exists():
                raise DownloadError(f"A letöltés nem sikerült (a fájl nagyobb, mint {MAX_DOWNLOAD_SIZE}?).")

            try:
                await self.storage.upload(track_file, name)
            except Exception as error:
                print(f"Feltöltési hiba: {error!r}")
                raise DownloadError("A feltöltés a zenetárba nem sikerült.")

        lines = result.stdout.strip().splitlines()
        return lines[-1] if lines else None

    async def _prepare_temp_track(self, url: str) -> tuple[str, str]:
        """Ideiglenes számot készít a linkből. Visszaadja a tárhelykulcsot és a megjelenített nevet."""
        name = f"{TEMP_PREFIX}{hashlib.sha1(url.encode()).hexdigest()[:16]}"
        try:
            if await self.storage.exists(name):
                return name, url
        except Exception as error:
            print(f"Tárhely hiba: {error!r}")
            raise DownloadError("Nem sikerült elérni a zenetárat.")

        if self.download_lock.locked():
            raise DownloadError("Már folyik egy letöltés, próbáld újra később.")
        async with self.download_lock:
            title = await self._download_to_storage(url, name)
        return name, title or url

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
        if (
            not separator
            or not is_url(url)
            or not ALIAS_PATTERN.fullmatch(alias)
        ):
            await ctx.send("Használat: `/download <URL> <név>` (a név betű, szám, szóköz, `-` vagy `_`).")
            return

        if self.download_lock.locked():
            await ctx.send("Már folyik egy letöltés, próbáld újra később.")
            return

        async with self.download_lock:
            try:
                await self._download_to_storage(url, alias.lower())
            except DownloadError as error:
                await ctx.send(str(error))
                return

        await ctx.send(f"Letöltve: **{alias}**")

    @commands.hybrid_command(name="takarodj")
    async def takarodj(self, ctx: commands.Context) -> None:
        await self.leave.callback(self, ctx)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
