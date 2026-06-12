from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

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

PROJECT_ENV = "GOOGLE_DOCAI_PROJECT"
LOCATION_ENV = "GOOGLE_DOCAI_LOCATION"
PROCESSOR_ENV = "GOOGLE_DOCAI_PROCESSOR_ID"


def _anchor_range(text_anchor: Any) -> tuple[int, int] | None:
    segments = getattr(text_anchor, "text_segments", None) or []
    if not segments:
        return None
    starts = [int(getattr(s, "start_index", 0) or 0) for s in segments]
    ends = [int(s.end_index) for s in segments]
    return min(starts), max(ends)


def _anchor_text(full_text: str, text_anchor: Any) -> str:
    segments = getattr(text_anchor, "text_segments", None) or []
    parts = []
    for s in segments:
        start = int(getattr(s, "start_index", 0) or 0)
        parts.append(full_text[start : int(s.end_index)])
    return "".join(parts)


def _layout_bbox(layout: Any, page_width: float, page_height: float) -> BoundingBox | None:
    poly = getattr(layout, "bounding_poly", None)
    if poly is None:
        return None
    vertices = list(getattr(poly, "vertices", None) or [])
    if vertices:
        xs = [float(v.x or 0) for v in vertices]
        ys = [float(v.y or 0) for v in vertices]
        return BoundingBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
    normalized = list(getattr(poly, "normalized_vertices", None) or [])
    if normalized:
        xs = [float(v.x or 0) * page_width for v in normalized]
        ys = [float(v.y or 0) * page_height for v in normalized]
        return BoundingBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
    return None


def map_docai_document(docai_doc: Any) -> list[Page]:
    """Map a Document AI Document onto the Document contract.

    Lines and tokens both reference document.text via text anchors; tokens
    are matched to their line by anchor offset containment. Both carry
    confidences (0-1) on their layout.
    """
    full_text = docai_doc.text or ""
    pages: list[Page] = []

    for i, dp in enumerate(docai_doc.pages or []):
        dimension = getattr(dp, "dimension", None)
        width = float(dimension.width) if dimension else 0.0
        height = float(dimension.height) if dimension else 0.0

        tokens = []
        for token in getattr(dp, "tokens", None) or []:
            rng = _anchor_range(token.layout.text_anchor)
            if rng is None:
                continue
            tokens.append(
                (
                    rng[0],
                    Word(
                        text=_anchor_text(full_text, token.layout.text_anchor).strip(),
                        bbox=_layout_bbox(token.layout, width, height),
                        confidence=getattr(token.layout, "confidence", None),
                    ),
                )
            )

        blocks: list[Block] = []
        line_texts: list[str] = []
        for line in getattr(dp, "lines", None) or []:
            rng = _anchor_range(line.layout.text_anchor)
            if rng is None:
                continue
            line_words = [w for offset, w in tokens if rng[0] <= offset < rng[1]]
            confs = [w.confidence for w in line_words if w.confidence is not None]
            line_conf = getattr(line.layout, "confidence", None)
            text = _anchor_text(full_text, line.layout.text_anchor).strip()
            blocks.append(
                Block(
                    block_id=str(uuid.uuid4()),
                    block_type=BlockType.TEXT,
                    text=text,
                    bbox=_layout_bbox(line.layout, width, height),
                    confidence=(
                        sum(confs) / len(confs) if confs else line_conf
                    ),
                    words=line_words,
                )
            )
            line_texts.append(text)

        dim_unit = str(getattr(dimension, "unit", "") or "pixels").lower()
        pages.append(
            Page(
                page_number=int(getattr(dp, "page_number", 0) or i + 1) - 1,
                width=width or None,
                height=height or None,
                unit="pt" if "point" in dim_unit else "px",
                blocks=blocks,
                text="\n".join(line_texts),
            )
        )
    return pages


def _process_sync(
    project: str, location: str, processor_id: str,
    file_path: str, mime_type: str,
) -> Any:
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
    except ImportError as e:
        raise ImportError(
            "google-cloud-documentai is required for the Document AI parser. "
            "Install with: pip install docflow[gcp]"
        ) from e

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(
            api_endpoint=f"{location}-documentai.googleapis.com"
        )
    )
    name = client.processor_path(project, location, processor_id)
    with open(file_path, "rb") as f:
        content = f.read()

    try:
        result = client.process_document(
            request=documentai.ProcessRequest(
                name=name,
                raw_document=documentai.RawDocument(
                    content=content, mime_type=mime_type,
                ),
            )
        )
    except Exception as exc:
        raise ParsingError(f"Google Document AI failed: {exc}") from exc

    return result.document


class GoogleDocumentAIParser:
    """OCR via Google Document AI. Sends the file natively to a processor
    (use an OCR processor, e.g. the Document OCR type).

    Configuration defaults to the GOOGLE_DOCAI_PROJECT, GOOGLE_DOCAI_LOCATION
    and GOOGLE_DOCAI_PROCESSOR_ID environment variables; authentication uses
    standard Google application default credentials.
    """

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        processor_id: str | None = None,
    ):
        self.project = project or os.environ.get(PROJECT_ENV, "")
        self.location = location or os.environ.get(LOCATION_ENV, "us")
        self.processor_id = processor_id or os.environ.get(PROCESSOR_ENV, "")

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")
        if not self.project or not self.processor_id:
            raise ParsingError(
                "Google Document AI configuration missing. Pass project/processor_id "
                f"or set {PROJECT_ENV} and {PROCESSOR_ENV}."
            )

        mime_type = document.metadata.mime_type or "application/pdf"
        loop = asyncio.get_event_loop()
        docai_doc = await loop.run_in_executor(
            _EXECUTOR,
            partial(
                _process_sync, self.project, self.location,
                self.processor_id, file_path, mime_type,
            ),
        )

        document.pages = map_docai_document(docai_doc)
        document.raw_text = "\n\n".join(p.text for p in document.pages)
        document.metadata.page_count = len(document.pages)
        document.status = "parsed"
        return document
