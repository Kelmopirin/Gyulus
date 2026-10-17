"""Letöltő worker: otthoni (lakossági) IP-ről dolgozza fel a bot letöltési kéréseit.

A bot a bucket `jobs/` mappájába írja a kéréseket, a worker letölti a videót,
feltölti a megadott kulcsra, és eredményt ír vissza.
"""

import asyncio
import re
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from downloader import DownloadError, download_mp3, is_url  # noqa: E402
from storage import JOBS_PREFIX, JOB_SUFFIX, Storage, result_key  # noqa: E402

POLL_INTERVAL = 5
TARGET_PATTERN = re.compile(r"temp/[0-9a-f]{16}|[\w\- ]{1,64}")


async def run_job(storage: Storage, job: dict) -> dict:
    url = job.get("url")
    target = job.get("key")
    if not isinstance(url, str) or not is_url(url):
        return {"ok": False, "error": "Érvénytelen link."}
    if not isinstance(target, str) or not TARGET_PATTERN.fullmatch(target):
        return {"ok": False, "error": "Érvénytelen név."}

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            track_file, title = await download_mp3(url, Path(temp_dir))
            await storage.upload(track_file, target)
    except DownloadError as error:
        return {"ok": False, "error": str(error)}
    except Exception as error:
        print(f"Feltöltési hiba: {error!r}")
        return {"ok": False, "error": "A feltöltés a zenetárba nem sikerült."}
    return {"ok": True, "title": title}


async def handle(storage: Storage, key: str) -> None:
    job_id = key[len(JOBS_PREFIX) : -len(JOB_SUFFIX)]
    try:
        job = await storage.get_json(key)
    except ValueError:
        job = None
    # A kérés törlése jelzi, hogy a feldolgozás megkezdődött.
    await storage.delete(key)
    if not isinstance(job, dict):
        return

    print(f"Letöltés: {job.get('url')} -> {job.get('key')}")
    result = await run_job(storage, job)
    await storage.put_json(result_key(job_id), result)
    print("Kész." if result["ok"] else f"Hiba: {result['error']}")


async def main() -> None:
    storage = Storage()
    print("Worker elindult, kérések figyelése...")
    while True:
        try:
            for key in await storage.list_keys(JOBS_PREFIX, JOB_SUFFIX):
                await handle(storage, key)
        except Exception as error:
            print(f"Worker hiba: {error!r}")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Worker leállítva.")
