"""Object storage port with local-filesystem and S3-compatible adapters."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root) + os.sep):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """S3 / MinIO / any S3-compatible store; server-side encryption with KMS when configured."""

    def __init__(self, bucket: str, endpoint_url: str | None, region: str, kms_key_id: str | None) -> None:
        import boto3

        self._client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        self.bucket = bucket
        self.kms_key_id = kms_key_id

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra: dict[str, str] = {"ContentType": content_type}
        if self.kms_key_id:
            extra.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=self.kms_key_id)
        else:
            extra["ServerSideEncryption"] = "AES256"
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region, s.s3_kms_key_id)
    return LocalStorage(s.storage_local_path)
