from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from docuflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    Page,
    Word,
)
from docuflow.errors import ParsingError

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

ENDPOINT_ENV = "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
KEY_ENV = "AZURE_DOCUMENT_INTELLIGENCE_KEY"


def _polygon_to_bbox(
    polygon: list[float] | None, scale: float = 1.0,
) -> BoundingBox | None:
    if not polygon or len(polygon) < 4:
        return None
    xs = polygon[0::2]
    ys = polygon[1::2]
    return BoundingBox(
        x0=min(xs) * scale, y0=min(ys) * scale,
        x1=max(xs) * scale, y1=max(ys) * scale,
    )


def _span_offsets(spans: Any) -> list[tuple[int, int]]:
    return [(s.offset, s.offset + s.length) for s in (spans or [])]


def map_analyze_result(result: Any) -> list[Page]:
    """Map an Azure Document Intelligence AnalyzeResult onto the Document contract.

    DI lines carry no confidence of their own; the line confidence is the
    mean of its word confidences, matched to lines via text spans.

    Coordinates convert to the canonical space: DI reports PDFs in inches
    (scaled x72 to points); image inputs report pixels, kept as-is with
    unit="px" since the physical size is unknown.
    """
    pages: list[Page] = []
    for di_page in result.pages or []:
        di_unit = str(getattr(di_page, "unit", "") or "inch")
        scale = 72.0 if di_unit == "inch" else 1.0
        unit = "pt" if di_unit == "inch" else "px"

        words = []
        for w in di_page.words or []:
            offset = w.span.offset if w.span else -1
            words.append(
                (
                    offset,
                    Word(
                        text=w.content,
                        bbox=_polygon_to_bbox(getattr(w, "polygon", None), scale),
                        confidence=getattr(w, "confidence", None),
                    ),
                )
            )

        blocks: list[Block] = []
        line_texts: list[str] = []
        for line in di_page.lines or []:
            spans = _span_offsets(getattr(line, "spans", None))
            line_words = [
                word
                for offset, word in words
                if any(start <= offset < end for start, end in spans)
            ]
            confs = [w.confidence for w in line_words if w.confidence is not None]
            blocks.append(
                Block(
                    block_id=str(uuid.uuid4()),
                    block_type=BlockType.TEXT,
                    text=line.content,
                    bbox=_polygon_to_bbox(getattr(line, "polygon", None), scale),
                    confidence=sum(confs) / len(confs) if confs else None,
                    words=line_words,
                )
            )
            line_texts.append(line.content)

        page_width = getattr(di_page, "width", None)
        page_height = getattr(di_page, "height", None)
        pages.append(
            Page(
                page_number=(di_page.page_number or 1) - 1,
                width=page_width * scale if page_width is not None else None,
                height=page_height * scale if page_height is not None else None,
                unit=unit,
                blocks=blocks,
                text="\n".join(line_texts),
            )
        )
    return pages


def _analyze_sync(endpoint: str, key: str, model: str, file_path: str) -> Any:
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as e:
        raise ImportError(
            "azure-ai-documentintelligence is required for the Azure DI parser. "
            "Install with: pip install docuflow[azure]"
        ) from e

    client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))
    try:
        with open(file_path, "rb") as f:
            poller = client.begin_analyze_document(model, body=f)
        return poller.result()
    except Exception as exc:
        raise ParsingError(f"Azure Document Intelligence failed: {exc}") from exc


class AzureDocumentIntelligenceParser:
    """OCR via Azure Document Intelligence. Sends the file natively (PDF,
    images, Office formats) — no local rendering needed.

    Credentials default to the AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and
    AZURE_DOCUMENT_INTELLIGENCE_KEY environment variables.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        key: str | None = None,
        model: str = "prebuilt-read",
    ):
        self.endpoint = endpoint or os.environ.get(ENDPOINT_ENV, "")
        self.key = key or os.environ.get(KEY_ENV, "")
        self.model = model

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")
        if not self.endpoint or not self.key:
            raise ParsingError(
                "Azure Document Intelligence credentials missing. Pass endpoint/key "
                f"or set {ENDPOINT_ENV} and {KEY_ENV}."
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _EXECUTOR,
            partial(_analyze_sync, self.endpoint, self.key, self.model, file_path),
        )

        document.pages = map_analyze_result(result)
        document.raw_text = "\n\n".join(p.text for p in document.pages)
        document.metadata.page_count = len(document.pages)
        document.status = "parsed"
        return document
