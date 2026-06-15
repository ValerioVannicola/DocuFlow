from __future__ import annotations

from pathlib import Path
from typing import Literal

from docuflow.errors import UnsupportedFileTypeError

MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".xml": "application/xml",
    ".eml": "message/rfc822",
}

SourceKind = Literal["pdf", "image", "text", "office", "spreadsheet", "email"]

PDF_MIME_TYPES = {"application/pdf"}
IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
    "image/gif",
    "image/webp",
}
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
}
OFFICE_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SPREADSHEET_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
EMAIL_MIME_TYPES = {"message/rfc822"}


def detect_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in MIME_TYPES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {ext!r} for file {path.name}"
        )
    return MIME_TYPES[ext]


def source_kind_for_mime(mime_type: str) -> SourceKind:
    if mime_type in PDF_MIME_TYPES:
        return "pdf"
    if mime_type in IMAGE_MIME_TYPES:
        return "image"
    if mime_type in TEXT_MIME_TYPES:
        return "text"
    if mime_type in OFFICE_MIME_TYPES:
        return "office"
    if mime_type in SPREADSHEET_MIME_TYPES:
        return "spreadsheet"
    if mime_type in EMAIL_MIME_TYPES:
        return "email"
    raise UnsupportedFileTypeError(f"Unsupported MIME type: {mime_type!r}")


def detect_source_kind(path: Path) -> SourceKind:
    return source_kind_for_mime(detect_mime_type(path))
