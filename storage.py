import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

PRESIGNED_URL_TTL = 6 * 60 * 60
TRACK_SUFFIX = ".mp3"
TEMP_PREFIX = "temp/"


class Storage:
    """S3-kompatibilis (Cloudflare R2, Backblaze B2, AWS S3) zenetár."""

    def __init__(self) -> None:
        self.bucket = os.environ["S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            region_name=os.getenv("S3_REGION", "auto"),
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def _list_tracks(self) -> list[str]:
        names = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                if key.startswith(TEMP_PREFIX):
                    continue
                if key.lower().endswith(TRACK_SUFFIX):
                    names.append(key[: -len(TRACK_SUFFIX)])
        return sorted(names, key=str.lower)

    def _exists(self, name: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=f"{name}{TRACK_SUFFIX}")
        except self.client.exceptions.ClientError:
            return False
        return True

    def _cleanup_temp(self, max_age: timedelta) -> int:
        cutoff = datetime.now(timezone.utc) - max_age
        expired = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=TEMP_PREFIX):
            for item in page.get("Contents", []):
                if item["LastModified"] < cutoff:
                    expired.append({"Key": item["Key"]})
        for start in range(0, len(expired), 1000):
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": expired[start : start + 1000], "Quiet": True},
            )
        return len(expired)

    def _presigned_url(self, name: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": f"{name}{TRACK_SUFFIX}"},
            ExpiresIn=PRESIGNED_URL_TTL,
        )

    def _upload(self, path: Path, name: str) -> None:
        self.client.upload_file(
            str(path),
            self.bucket,
            f"{name}{TRACK_SUFFIX}",
            Config=TransferConfig(max_concurrency=1, multipart_threshold=64 * 1024 * 1024),
        )

    async def list_tracks(self) -> list[str]:
        return await asyncio.to_thread(self._list_tracks)

    async def presigned_url(self, name: str) -> str:
        return await asyncio.to_thread(self._presigned_url, name)

    async def upload(self, path: Path, name: str) -> None:
        await asyncio.to_thread(self._upload, path, name)

    async def exists(self, name: str) -> bool:
        return await asyncio.to_thread(self._exists, name)

    async def cleanup_temp(self, max_age: timedelta) -> int:
        return await asyncio.to_thread(self._cleanup_temp, max_age)
