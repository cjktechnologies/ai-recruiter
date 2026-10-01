"""Object storage port with local-filesystem and Google Cloud Storage adapters."""

from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

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


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_backend == "gcs":
        if not s.gcs_bucket:
            raise RuntimeError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
        return GCSStorage(s.gcs_bucket, s.gcp_project_id, s.gcs_kms_key_name)
    return LocalStorage(s.storage_local_path)
