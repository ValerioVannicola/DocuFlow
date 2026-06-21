from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from docuflow.documents.models import Block, BlockType, Document, Page
from docuflow.errors import ParsingError

_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _parse_with_markitdown(file_path: str) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise ImportError(
            "markitdown is required for Markitdown parsing. "
            "Install with: pip install docuflow[markitdown]"
        ) from e

    try:
        result = MarkItDown().convert(file_path)
    except Exception as exc:
        raise ParsingError(f"Markitdown failed to convert: {file_path}") from exc

    return result.markdown or ""


class MarkitdownParser:
    """Converts any Microsoft Markitdown-supported file to Markdown text.

    Markitdown (https://github.com/microsoft/markitdown) handles a very wide
    format range (PDF, Office, HTML, images, audio transcripts, ZIP, ...) but
    is a one-shot text converter, not a layout/OCR engine: it returns a single
    Markdown string with no page boundaries, no bounding boxes, and no
    confidence scoring. Output lands as one page with one text block — the
    same shape DocuFlow uses for plain-text ingestion — so it slots into the
    rest of the pipeline like any other parser, just without OCR/evidence
    bbox precision.
    """

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        import asyncio

        loop = asyncio.get_event_loop()
        markdown = await loop.run_in_executor(
            _EXECUTOR, partial(_parse_with_markitdown, file_path)
        )
        markdown = markdown.strip()

        block = Block(
            block_id=str(uuid.uuid4()),
            block_type=BlockType.TEXT,
            text=markdown,
        )
        document.pages = [Page(page_number=0, blocks=[block], text=markdown)]
        document.raw_text = markdown
        document.metadata.page_count = 1
        document.status = "parsed"
        return document
