from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from docuflow._sync import run_sync
from docuflow.documents.models import Block, BlockType, Document, DocumentMetadata, Page
from docuflow.ingestion.mime import detect_mime_type, source_kind_for_mime

_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "latin-1")


async def _compute_file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    async with aiofiles.open(path, "rb") as f:
        while chunk := await f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


async def _read_text_file(path: Path) -> str:
    async with aiofiles.open(path, "rb") as file:
        data = await file.read()
    for encoding in _TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _text_document_pages(text: str) -> list[Page]:
    block = Block(
        block_id=str(uuid.uuid4()),
        block_type=BlockType.TEXT,
        text=text,
    )
    return [Page(page_number=0, blocks=[block], text=text)]


def _image_document_pages(path: Path) -> list[Page]:
    try:
        from PIL import Image
    except ImportError:
        return [Page(page_number=0, image_path=str(path), unit="px")]

    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return [Page(page_number=0, image_path=str(path), unit="px")]

    return [
        Page(
            page_number=0,
            width=float(width),
            height=float(height),
            unit="px",
            image_path=str(path),
        )
    ]


async def ingest_file(path: str | Path) -> Document:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    mime_type = detect_mime_type(path)
    source_kind = source_kind_for_mime(mime_type)
    file_hash = await _compute_file_hash(path)
    file_size = os.path.getsize(path)

    metadata = DocumentMetadata(
        file_name=path.name,
        file_path=str(path),
        file_size=file_size,
        file_hash=file_hash,
        mime_type=mime_type,
        source_uri=path.as_uri(),
        extra={"source_kind": source_kind},
    )

    document = Document(
        id=str(uuid.uuid4()),
        metadata=metadata,
    )

    if source_kind in ("text", "email"):
        text = await _read_text_file(path)
        document.pages = _text_document_pages(text)
        document.raw_text = text
        document.metadata.page_count = 1
        document.status = "parsed"
    elif source_kind == "image":
        document.pages = _image_document_pages(path)
        document.metadata.page_count = 1

    return document


async def ingest_folder(
    path: str | Path,
    pattern: str = "**/*.pdf",
) -> AsyncIterator[Document]:
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Directory not found: {folder}")

    for file_path in sorted(folder.glob(pattern)):
        if file_path.is_file():
            yield await ingest_file(file_path)


def ingest_file_sync(path: str | Path) -> Document:
    return run_sync(ingest_file(path))
