from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from docflow._sync import run_sync
from docflow.documents.models import Document, DocumentMetadata
from docflow.ingestion.mime import detect_mime_type


async def _compute_file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    async with aiofiles.open(path, "rb") as f:
        while chunk := await f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


async def ingest_file(path: str | Path) -> Document:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    mime_type = detect_mime_type(path)
    file_hash = await _compute_file_hash(path)
    file_size = os.path.getsize(path)

    metadata = DocumentMetadata(
        file_name=path.name,
        file_path=str(path),
        file_size=file_size,
        file_hash=file_hash,
        mime_type=mime_type,
        source_uri=path.as_uri(),
    )

    return Document(
        id=str(uuid.uuid4()),
        metadata=metadata,
    )


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
