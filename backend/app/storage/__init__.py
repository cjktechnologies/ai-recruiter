"""Object storage port with local-filesystem, Google Cloud Storage and Vercel Blob adapters."""

from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

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


class GCSStorage:
    """Google Cloud Storage.

    Credentials come from Application Default Credentials (GKE Workload Identity in the cluster).
    Encryption at rest uses the bucket's default Cloud KMS key; ``kms_key_name`` pins it per object
    as well. Setting ``STORAGE_EMULATOR_HOST`` (local compose) targets a fake-gcs-server instead.
    """

    def __init__(self, bucket: str, project: str | None, kms_key_name: str | None, client: Any = None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client(project=project)
        self._bucket = client.bucket(bucket)
        self.kms_key_name = kms_key_name

    def put(self, key: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(key, kms_key_name=self.kms_key_name)
        blob.upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return bytes(self._bucket.blob(key).download_as_bytes())

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        with contextlib.suppress(NotFound):
            self._bucket.blob(key).delete()


class VercelBlobStorage:
    """Vercel Blob, private access only (every read is authenticated with the store token).

    Uses the Blob REST API directly (as ``@vercel/blob`` does): objects are written at their exact
    key (no random suffix) so they can be read and deleted by key later.
    """

    API_URL = "https://vercel.com/api/blob"
    API_VERSION = "12"

    def __init__(self, token: str, client: Any = None, api_url: str | None = None) -> None:
        parts = token.split("_")
        if len(parts) < 5 or not token.startswith("vercel_blob_rw_"):
            raise ValueError("BLOB_READ_WRITE_TOKEN is not a Vercel Blob read-write token")
        self._token = token
        self.store_id = parts[3]
        self.api_url = (api_url or os.environ.get("VERCEL_BLOB_API_URL") or self.API_URL).rstrip("/")
        if client is None:
            import httpx

            client = httpx.Client(timeout=60.0)
        self._http = client

    def _headers(self, **extra: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._token}",
            "x-api-version": self.API_VERSION,
            "x-vercel-blob-store-id": self.store_id,
            **extra,
        }

    def url(self, key: str) -> str:
        return f"https://{self.store_id}.private.blob.vercel-storage.com/{quote(key)}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        res = self._http.put(
            f"{self.api_url}/",
            params={"pathname": key},
            content=data,
            headers=self._headers(
                **{
                    "x-vercel-blob-access": "private",
                    "x-add-random-suffix": "0",
                    "x-allow-overwrite": "1",
                    "x-content-type": content_type,
                }
            ),
        )
        res.raise_for_status()

    def get(self, key: str) -> bytes:
        res = self._http.get(self.url(key), headers={"authorization": f"Bearer {self._token}"})
        res.raise_for_status()
        return bytes(res.content)

    def delete(self, key: str) -> None:
        res = self._http.post(
            f"{self.api_url}/delete",
            json={"urls": [self.url(key)]},
            headers=self._headers(**{"content-type": "application/json"}),
        )
        res.raise_for_status()


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_backend == "gcs":
        if not s.gcs_bucket:
            raise RuntimeError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
        return GCSStorage(s.gcs_bucket, s.gcp_project_id, s.gcs_kms_key_name)
    if s.storage_backend == "vercel_blob":
        assert s.blob_read_write_token is not None  # enforced by Settings
        return VercelBlobStorage(s.blob_read_write_token.get_secret_value())
    return LocalStorage(s.storage_local_path)
