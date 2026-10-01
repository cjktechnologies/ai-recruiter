"""Cloud adapters: Cloud Storage and Vercel Blob documents, Redis TLS options, DB URLs and client IPs."""

from __future__ import annotations

import json
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


# --- Vercel ------------------------------------------------------------------------------------


def test_vercel_blob_storage_uses_private_rest_api() -> None:
    import httpx

    from app.storage import VercelBlobStorage

    store: dict[str, bytes] = {}
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["authorization"] == "Bearer vercel_blob_rw_store123_secret"
        if req.method == "PUT":
            assert req.url.host == "vercel.com" and req.url.path == "/api/blob/"
            assert req.headers["x-vercel-blob-access"] == "private"
            assert req.headers["x-add-random-suffix"] == "0"
            assert req.headers["x-api-version"] == "12"
            store[req.url.params["pathname"]] = req.content
            return httpx.Response(200, json={"pathname": req.url.params["pathname"]})
        if req.method == "GET":
            assert req.url.host == "store123.private.blob.vercel-storage.com"
            key = req.url.path.lstrip("/")
            return httpx.Response(200, content=store[key]) if key in store else httpx.Response(404)
        assert req.method == "POST" and req.url.path == "/api/blob/delete"
        for url in json.loads(req.content)["urls"]:
            store.pop(httpx.URL(url).path.lstrip("/"), None)
        return httpx.Response(200, json={})

    s = VercelBlobStorage("vercel_blob_rw_store123_secret", client=httpx.Client(transport=httpx.MockTransport(handler)))
    s.put("org/1/cv.pdf", b"%PDF", "application/pdf")
    assert seen[0].headers["x-content-type"] == "application/pdf"
    assert s.get("org/1/cv.pdf") == b"%PDF"
    s.delete("org/1/cv.pdf")
    assert store == {}
    with pytest.raises(httpx.HTTPStatusError):
        s.get("org/1/cv.pdf")


def test_vercel_blob_rejects_non_blob_token() -> None:
    from app.storage import VercelBlobStorage

    with pytest.raises(ValueError):
        VercelBlobStorage("not-a-token")


def test_provider_database_urls_get_the_psycopg_driver() -> None:
    assert Settings(database_url="postgres://u:p@h/db?sslmode=require").database_url == (
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    )
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgresql+psycopg://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"


def test_vercel_blob_backend_requires_token() -> None:
    with pytest.raises(ValueError, match="BLOB_READ_WRITE_TOKEN"):
        Settings(storage_backend="vercel_blob")


def test_public_ca_redis_tls_checks_hostname() -> None:
    assert Settings(redis_url="rediss://default:pw@eu1.upstash.io:6379").redis_ssl_options() == {
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
        "ssl_check_hostname": True,
    }


def test_client_ip_trusts_bff_header_only_with_proxy_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from app.api.middleware import client_ip
    from app.core.config import get_settings

    def req(**headers: str) -> Request:
        raw = [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": ("10.1.1.1", 1234)})

    monkeypatch.setenv("PROXY_SHARED_SECRET", "bff-secret-value")
    get_settings.cache_clear()
    try:
        assert client_ip(req(x_client_ip="203.0.113.7", x_proxy_secret="bff-secret-value")) == "203.0.113.7"
        # Wrong or missing secret: the claimed IP is ignored.
        assert client_ip(req(x_client_ip="203.0.113.7", x_proxy_secret="guess")) == "10.1.1.1"
        assert client_ip(req(x_client_ip="203.0.113.7", x_forwarded_for="198.51.100.2")) == "198.51.100.2"
    finally:
        monkeypatch.delenv("PROXY_SHARED_SECRET")
        get_settings.cache_clear()
    assert client_ip(req(x_client_ip="203.0.113.7", x_proxy_secret="bff-secret-value")) == "10.1.1.1"
