"""Google Cloud adapters: Cloud Storage documents and Memorystore (TLS) Redis options."""

from __future__ import annotations

import os
import ssl
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.storage import GCSStorage


class _FakeBlob:
    def __init__(self, store: dict[str, tuple[bytes, str | None, str | None]], name: str, kms: str | None) -> None:
        self.store, self.name, self.kms = store, name, kms

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        self.store[self.name] = (data, content_type, self.kms)

    def download_as_bytes(self) -> bytes:
        return self.store[self.name][0]

    def delete(self) -> None:
        from google.api_core.exceptions import NotFound

        if self.name not in self.store:
            raise NotFound("missing")
        del self.store[self.name]


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, tuple[bytes, str | None, str | None]] = {}
        self.bucket_name: str | None = None

    def bucket(self, name: str) -> Any:
        self.bucket_name = name
        client = self

        class _Bucket:
            def blob(self, key: str, kms_key_name: str | None = None) -> _FakeBlob:
                return _FakeBlob(client.store, key, kms_key_name)

        return _Bucket()


def test_gcs_storage_round_trip_with_cmek() -> None:
    key = "projects/p/locations/europe-west1/keyRings/r/cryptoKeys/data"
    client = _FakeClient()
    storage = GCSStorage("docs", None, key, client=client)
    storage.put("org/cv.pdf", b"%PDF-1.7", "application/pdf")
    assert client.bucket_name == "docs"
    assert client.store["org/cv.pdf"] == (b"%PDF-1.7", "application/pdf", key)
    assert storage.get("org/cv.pdf") == b"%PDF-1.7"
    storage.delete("org/cv.pdf")
    storage.delete("org/cv.pdf")  # idempotent, like the local adapter
    assert client.store == {}


@pytest.mark.skipif(not os.environ.get("STORAGE_EMULATOR_HOST"), reason="needs a Cloud Storage emulator")
def test_gcs_storage_against_emulator() -> None:
    from google.cloud import storage as gcs

    bucket = f"test-{uuid.uuid4().hex[:12]}"
    gcs.Client(project="test").create_bucket(bucket)
    s = GCSStorage(bucket, "test", None)
    s.put("a/b.txt", b"hello", "text/plain")
    assert s.get("a/b.txt") == b"hello"
    s.delete("a/b.txt")
    s.delete("a/b.txt")


def test_redis_tls_options_only_for_rediss() -> None:
    assert Settings(redis_url="redis://localhost:6379/0").redis_ssl_options() == {}
    opts = Settings(
        redis_url="rediss://:pw@10.0.0.3:6378/0", redis_tls_ca_cert="/etc/redis-tls/ca.pem"
    ).redis_ssl_options()
    assert opts == {
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
        "ssl_check_hostname": False,
        "ssl_ca_certs": "/etc/redis-tls/ca.pem",
    }
