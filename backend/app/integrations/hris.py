"""HRIS / payroll handoff and job-board publishing via signed webhooks.

Most HRIS products (Workday, BambooHR, SAP SuccessFactors, Personio) expose either REST APIs or
integration-platform webhooks; the platform posts a canonical, HMAC-signed payload which an
integration layer (or the vendor's inbound API) consumes. Signature: ``X-Signature: sha256=<hex>``.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.errors import ExternalServiceError


@dataclass
class WebhookResult:
    status_code: int
    external_id: str | None


def sign_payload(secret: str, body: bytes, timestamp: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def post_signed_webhook(url: str, secret: str, event: str, payload: dict, timeout: float = 20) -> WebhookResult:
    body = json.dumps({"event": event, "id": uuid.uuid4().hex, "data": payload}, default=str).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Event": event,
        "X-Timestamp": ts,
        "X-Signature": sign_payload(secret, body, ts),
        "Idempotency-Key": hashlib.sha256(body).hexdigest(),
    }
    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Webhook delivery failed for {event}") from exc
    ext = None
    with contextlib.suppress(ValueError):
        ext = resp.json().get("id") or resp.json().get("employee_id")
    return WebhookResult(resp.status_code, ext)


def verify_inbound_signature(secret: str, body: bytes, timestamp: str, signature: str, tolerance: int = 300) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > tolerance:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sign_payload(secret, body, timestamp), signature)
