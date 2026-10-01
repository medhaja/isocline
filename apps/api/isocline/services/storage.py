"""Object storage abstraction. Local filesystem for development; any S3-compatible store in production."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from isocline.core.config import get_settings


class Storage:
    async def put(self, data: bytes, suffix: str = "") -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("Invalid storage key")
        return p

    async def put(self, data: bytes, suffix: str = "") -> str:
        key = f"{uuid.uuid4().hex[:2]}/{uuid.uuid4().hex}{suffix}"  # safe internal filename
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass


class S3Storage(Storage):
    """S3-compatible storage (AWS S3, MinIO, R2). boto3 is imported lazily so it stays optional."""

    def __init__(self, endpoint: str | None, bucket: str):
        import boto3  # type: ignore
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint)

    async def put(self, data: bytes, suffix: str = "") -> str:
        import asyncio
        key = f"uploads/{uuid.uuid4().hex}{suffix}"
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data)
        return key

    async def get(self, key: str) -> bytes:
        import asyncio
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    async def delete(self, key: str) -> None:
        import asyncio
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage(s.s3_endpoint, s.s3_bucket or "isocline") if s.storage_backend == "s3" else LocalStorage(s.storage_local_path)
    return _storage
