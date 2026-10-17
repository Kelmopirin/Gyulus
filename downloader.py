import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MAX_DOWNLOAD_SIZE = "100M"
DOWNLOAD_TIMEOUT = 600


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
    """A letöltési kísérletek sorrendben, az egyszerűbbtől a bonyolultabbig."""
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


async def download_mp3(url: str, directory: Path) -> tuple[Path, str | None]:
    """Letölti a linket mp3-ként a mappába. Visszaadja a fájlt és a címet, ha elérhető."""
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
                    str(directory / "track.%(ext)s"),
                    "--",
                    url,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=DOWNLOAD_TIMEOUT,
            )
            break
        except subprocess.CalledProcessError as error:
            print(f"yt-dlp hiba ({label}): {error.stderr[-1500:]}")
        except subprocess.TimeoutExpired:
            print(f"yt-dlp időtúllépés ({label})")
    if result is None:
        raise DownloadError("A letöltés nem sikerült.")

    track_file = directory / "track.mp3"
    if not track_file.exists():
        raise DownloadError(f"A letöltés nem sikerült (a fájl nagyobb, mint {MAX_DOWNLOAD_SIZE}?).")

    lines = result.stdout.strip().splitlines()
    return track_file, (lines[-1] if lines else None)
