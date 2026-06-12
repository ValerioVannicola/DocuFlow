from __future__ import annotations

from pathlib import Path

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
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".eml": "message/rfc822",
}


def detect_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in MIME_TYPES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {ext!r} for file {path.name}"
        )
    return MIME_TYPES[ext]
