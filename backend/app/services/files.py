"""Secure file intake: size/type allow-listing, magic-byte verification, macro/active content
rejection, and malware scanning via ClamAV (clamd INSTREAM protocol)."""

from __future__ import annotations

import io
import re
import socket
import struct
import zipfile
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import UnsafeContent, ValidationFailed
from app.domain.enums import ScanStatus

ALLOWED: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "text/plain": (".txt",),
    "text/markdown": (".md",),
}
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass
class ScanResult:
    status: ScanStatus
    detail: str | None = None


def safe_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    base = _SAFE_NAME.sub("_", base).strip(" .") or "document"
    return base[:200]


def sniff_content_type(data: bytes, declared: str, filename: str) -> str:
    """Determine the real type from magic bytes; reject mismatches with the declared type/extension."""
    fname = filename.lower()
    if data.startswith(b"%PDF-"):
        real = "application/pdf"
    elif data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile as exc:
            raise UnsafeContent("Corrupt archive") from exc
        if "word/document.xml" not in names:
            raise UnsafeContent("Unsupported archive type")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise UnsafeContent("Documents with macros are not accepted")
        real = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsafeContent("Unsupported or binary file type") from exc
        real = "text/markdown" if fname.endswith(".md") else "text/plain"
    if not any(fname.endswith(ext) for ext in ALLOWED[real]):
        raise UnsafeContent("File extension does not match file content")
    if declared and declared not in (real, "application/octet-stream") and not (
        declared.startswith("text/") and real.startswith("text/")
    ):
        raise UnsafeContent("Declared content type does not match file content")
    if real == "application/pdf" and re.search(rb"/(JavaScript|JS|Launch|EmbeddedFile)\b", data):
        raise UnsafeContent("PDFs with active content are not accepted")
    return real


def validate_upload(data: bytes, declared: str, filename: str) -> tuple[str, str]:
    s = get_settings()
    if not data:
        raise ValidationFailed("Empty file")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ValidationFailed(f"File exceeds {s.max_upload_mb} MB limit")
    name = safe_filename(filename)
    return sniff_content_type(data, declared, name), name


def _clamd_scan(host: str, port: int, data: bytes, timeout: float = 30.0) -> ScanResult:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), 8192):
            chunk = data[i: i + 8192]
            sock.sendall(struct.pack("!L", len(chunk)) + chunk)
        sock.sendall(struct.pack("!L", 0))
        reply = sock.recv(4096).decode(errors="replace").strip("\0\n ")
    if reply.endswith("OK"):
        return ScanResult(ScanStatus.CLEAN)
    if "FOUND" in reply:
        return ScanResult(ScanStatus.INFECTED, reply.split(":", 1)[-1].strip())
    return ScanResult(ScanStatus.ERROR, reply[:200])


def scan_bytes(data: bytes) -> ScanResult:
    s = get_settings()
    if EICAR in data:
        return ScanResult(ScanStatus.INFECTED, "Eicar-Test-Signature")
    if s.clamav_host:
        try:
            return _clamd_scan(s.clamav_host, s.clamav_port, data)
        except OSError as exc:
            return ScanResult(ScanStatus.ERROR, f"scanner unavailable: {type(exc).__name__}")
    if s.require_malware_scan:
        return ScanResult(ScanStatus.ERROR, "malware scanner not configured")
    return ScanResult(ScanStatus.CLEAN, "no scanner configured (signature check only)")
