import asyncio
import hashlib
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from pathlib import PurePath

from app.core.config import get_settings

settings = get_settings()

ALLOWED_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MIME_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}


@dataclass(frozen=True, slots=True)
class DocumentInspection:
    content_type: str
    page_count: int
    sha256: str
    warnings: tuple[str, ...] = ()


def safe_filename(filename: str) -> str:
    value = PurePath(filename.replace("\\", "/")).name
    value = re.sub(r"[\x00-\x1f\x7f]+", "_", value).strip().strip(".")
    if not value:
        raise ValueError("invalid_document_filename")
    return value[:255]


def validate_upload_metadata(
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str | None,
) -> tuple[str, str]:
    normalized_name = safe_filename(filename)
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise ValueError("unsupported_document_type")
    if PurePath(normalized_name).suffix.lower() not in MIME_EXTENSIONS[normalized_type]:
        raise ValueError("document_extension_mime_mismatch")
    if size_bytes <= 0:
        raise ValueError("empty_document")
    if size_bytes > settings.document_max_file_bytes:
        raise ValueError("document_too_large")
    if sha256 is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
        raise ValueError("invalid_document_sha256")
    return normalized_name, normalized_type


def sniff_content_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _inspect_with_fitz(content: bytes, content_type: str) -> int:
    import fitz

    filetype = "pdf" if content_type == "application/pdf" else content_type.split("/", 1)[1]
    try:
        document = fitz.open(stream=content, filetype=filetype)
    except Exception as exc:
        raise ValueError("malformed_document") from exc
    try:
        if document.needs_pass:
            raise ValueError("encrypted_pdf_not_supported")
        page_count = len(document)
        if page_count < 1:
            raise ValueError("empty_document")
        if page_count > settings.document_max_pdf_pages:
            raise ValueError("pdf_page_limit_exceeded")
        if content_type == "application/pdf" and document.embfile_count() > 0:
            raise ValueError("pdf_embedded_files_not_allowed")

        total_pixels = 0
        for page in document:
            rect = page.rect
            width = max(1, int(rect.width * 2))
            height = max(1, int(rect.height * 2))
            if width > 20_000 or height > 20_000:
                raise ValueError("document_page_dimensions_too_large")
            total_pixels += width * height
            if total_pixels > settings.document_max_render_pixels:
                raise ValueError("document_render_budget_exceeded")
        return page_count
    finally:
        document.close()


async def _clamav_scan(content: bytes) -> tuple[bool, str | None]:
    host = settings.document_clamav_host
    if not host:
        return False, "virus_scan_not_configured"
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, settings.document_clamav_port),
            timeout=3,
        )
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(content), 64 * 1024):
            chunk = content[offset : offset + 64 * 1024]
            writer.write(struct.pack("!I", len(chunk)))
            writer.write(chunk)
        writer.write(struct.pack("!I", 0))
        await writer.drain()
        response = (await asyncio.wait_for(reader.read(4096), timeout=15)).decode(
            "utf-8", errors="replace"
        )
    except Exception as exc:
        if settings.document_clamav_required:
            raise RuntimeError("virus_scanner_unavailable") from exc
        return False, "virus_scan_unavailable"
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
    if "FOUND" in response:
        raise ValueError("malware_detected")
    if "OK" not in response:
        if settings.document_clamav_required:
            raise RuntimeError("virus_scan_failed")
        return False, "virus_scan_inconclusive"
    return True, None


async def inspect_document_content(
    content: bytes,
    declared_content_type: str,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> DocumentInspection:
    if not content:
        raise ValueError("empty_document")
    if len(content) > settings.document_max_file_bytes:
        raise ValueError("document_too_large")
    if expected_size is not None and len(content) != expected_size:
        raise ValueError("document_size_mismatch")
    detected = sniff_content_type(content)
    if detected is None:
        raise ValueError("unrecognized_document_magic")
    if detected != declared_content_type:
        raise ValueError("document_magic_mime_mismatch")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        raise ValueError("document_sha256_mismatch")

    page_count = await asyncio.to_thread(_inspect_with_fitz, content, detected)
    _, scan_warning = await _clamav_scan(content)
    warnings = (scan_warning,) if scan_warning else ()
    return DocumentInspection(
        content_type=detected,
        page_count=page_count,
        sha256=digest,
        warnings=warnings,
    )
