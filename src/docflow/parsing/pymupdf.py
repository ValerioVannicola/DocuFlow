from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from docflow.documents.models import Block, BlockType, BoundingBox, Document, Page
from docflow.errors import ParsingError

_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _parse_pdf_sync(file_path: str) -> list[Page]:
    try:
        import fitz
    except ImportError as e:
        raise ImportError(
            "PyMuPDF is required for PDF parsing. Install with: pip install docflow[pdf]"
        ) from e

    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise ParsingError(f"Failed to open PDF: {file_path}") from exc

    pages: list[Page] = []
    try:
        for page_num in range(len(doc)):
            fitz_page = doc[page_num]
            rect = fitz_page.rect

            blocks: list[Block] = []
            raw_dict = fitz_page.get_text("dict", sort=True)
            for block_data in raw_dict.get("blocks", []):
                block_bbox = block_data.get("bbox")
                bbox = None
                if block_bbox and len(block_bbox) == 4:
                    bbox = BoundingBox(
                        x0=block_bbox[0],
                        y0=block_bbox[1],
                        x1=block_bbox[2],
                        y1=block_bbox[3],
                    )

                block_type = BlockType.IMAGE if block_data.get("type") == 1 else BlockType.TEXT

                text_parts: list[str] = []
                if block_type == BlockType.TEXT:
                    for line in block_data.get("lines", []):
                        for span in line.get("spans", []):
                            text_parts.append(span.get("text", ""))

                block_text = " ".join(text_parts).strip()
                if not block_text and block_type == BlockType.TEXT:
                    continue

                blocks.append(
                    Block(
                        block_id=str(uuid.uuid4()),
                        block_type=block_type,
                        text=block_text,
                        bbox=bbox,
                    )
                )

            page_text = fitz_page.get_text("text").strip()
            pages.append(
                Page(
                    page_number=page_num,
                    width=rect.width,
                    height=rect.height,
                    blocks=blocks,
                    text=page_text,
                )
            )
    finally:
        doc.close()

    return pages


class PyMuPDFParser:
    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        import asyncio

        loop = asyncio.get_event_loop()
        pages = await loop.run_in_executor(_EXECUTOR, partial(_parse_pdf_sync, file_path))

        document.pages = pages
        document.raw_text = "\n\n".join(p.text for p in pages)
        document.metadata.page_count = len(pages)
        document.status = "parsed"
        return document
