from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import pairwise
from pathlib import Path

from docflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    Page,
    Word,
)
from docflow.errors import ParsingError

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Words whose tops are within this distance (PDF points) belong to one line.
_LINE_TOLERANCE = 3.0
# Horizontal gaps larger than this (PDF points) split a visual line into
# separate blocks — column boundaries, table label/value gaps. Without it,
# unrelated text across a two-column layout merges into one block.
_MAX_INLINE_GAP = 18.0


def _group_words_into_lines(raw_words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(raw_words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= _LINE_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])

    lines: list[list[dict]] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        current = [row[0]]
        for prev, cur in pairwise(row):
            if cur["x0"] - prev["x1"] > _MAX_INLINE_GAP:
                lines.append(current)
                current = [cur]
            else:
                current.append(cur)
        lines.append(current)
    return lines


def _parse_pdf_sync(file_path: str) -> list[Page]:
    try:
        import pdfplumber
    except ImportError as e:
        raise ImportError(
            "pdfplumber is required for PDF parsing. Install with: pip install docflow[pdf]"
        ) from e

    try:
        pdf = pdfplumber.open(file_path)
    except Exception as exc:
        raise ParsingError(f"Failed to open PDF: {file_path}") from exc

    pages: list[Page] = []
    try:
        for page_num, plumber_page in enumerate(pdf.pages):
            raw_words = plumber_page.extract_words()

            blocks: list[Block] = []
            for line in _group_words_into_lines(raw_words):
                words = [
                    Word(
                        text=w["text"],
                        bbox=BoundingBox(
                            x0=float(w["x0"]),
                            y0=float(w["top"]),
                            x1=float(w["x1"]),
                            y1=float(w["bottom"]),
                        ),
                    )
                    for w in line
                ]
                blocks.append(
                    Block(
                        block_id=str(uuid.uuid4()),
                        block_type=BlockType.TEXT,
                        text=" ".join(w.text for w in words),
                        bbox=BoundingBox(
                            x0=min(w.bbox.x0 for w in words),
                            y0=min(w.bbox.y0 for w in words),
                            x1=max(w.bbox.x1 for w in words),
                            y1=max(w.bbox.y1 for w in words),
                        ),
                        words=words,
                    )
                )

            for img in plumber_page.images:
                blocks.append(
                    Block(
                        block_id=str(uuid.uuid4()),
                        block_type=BlockType.IMAGE,
                        text="",
                        bbox=BoundingBox(
                            x0=float(img["x0"]),
                            y0=float(img["top"]),
                            x1=float(img["x1"]),
                            y1=float(img["bottom"]),
                        ),
                    )
                )

            page_text = plumber_page.extract_text() or ""
            pages.append(
                Page(
                    page_number=page_num,
                    width=float(plumber_page.width),
                    height=float(plumber_page.height),
                    blocks=blocks,
                    text=page_text.strip(),
                )
            )
    finally:
        pdf.close()

    return pages


class PdfplumberParser:
    """Native PDF text extraction via pdfplumber (MIT licensed).

    Produces line-level blocks with per-word bboxes, matching the OCR
    parsers' contract. Word/block confidence stays None — this reads the
    PDF text layer, no OCR runs.
    """

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
