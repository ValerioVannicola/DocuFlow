from __future__ import annotations

import asyncio
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from docuflow.constants import DEFAULT_DPI
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


def _geometry_to_bbox(
    geometry: dict, page_width: float, page_height: float,
) -> BoundingBox | None:
    box = geometry.get("BoundingBox") if geometry else None
    if not box:
        return None
    return BoundingBox(
        x0=box["Left"] * page_width,
        y0=box["Top"] * page_height,
        x1=(box["Left"] + box["Width"]) * page_width,
        y1=(box["Top"] + box["Height"]) * page_height,
    )


def map_textract_response(
    response: dict, page_number: int, page_width: float, page_height: float,
) -> Page:
    """Map a Textract DetectDocumentText response onto the Document contract.

    Textract LINE blocks reference their WORD children via CHILD
    relationships; both carry confidences (0-100).
    """
    by_id = {b["Id"]: b for b in response.get("Blocks", [])}

    blocks: list[Block] = []
    line_texts: list[str] = []
    for tb in response.get("Blocks", []):
        if tb.get("BlockType") != "LINE":
            continue

        child_ids: list[str] = []
        for rel in tb.get("Relationships", []):
            if rel.get("Type") == "CHILD":
                child_ids.extend(rel.get("Ids", []))

        words = []
        for cid in child_ids:
            wb = by_id.get(cid)
            if not wb or wb.get("BlockType") != "WORD":
                continue
            conf = wb.get("Confidence")
            words.append(
                Word(
                    text=wb.get("Text", ""),
                    bbox=_geometry_to_bbox(wb.get("Geometry"), page_width, page_height),
                    confidence=conf / 100.0 if conf is not None else None,
                )
            )

        confs = [w.confidence for w in words if w.confidence is not None]
        line_conf = tb.get("Confidence")
        text = tb.get("Text", "")
        blocks.append(
            Block(
                block_id=str(uuid.uuid4()),
                block_type=BlockType.TEXT,
                text=text,
                bbox=_geometry_to_bbox(tb.get("Geometry"), page_width, page_height),
                confidence=(
                    sum(confs) / len(confs) if confs
                    else line_conf / 100.0 if line_conf is not None else None
                ),
                words=words,
            )
        )
        line_texts.append(text)

    return Page(
        page_number=page_number,
        width=page_width,
        height=page_height,
        blocks=blocks,
        text="\n".join(line_texts),
    )


def _detect_sync(client: Any, image_bytes: bytes) -> dict:
    try:
        return client.detect_document_text(Document={"Bytes": image_bytes})
    except Exception as exc:
        raise ParsingError(f"AWS Textract failed: {exc}") from exc


class TextractParser:
    """OCR via AWS Textract. Renders pages to images locally and calls the
    synchronous DetectDocumentText API per page — no S3 bucket required.

    Credentials use the standard boto3 chain (env vars, profile, IAM role).
    """

    def __init__(self, region_name: str | None = None, dpi: int = DEFAULT_DPI):
        self.region_name = region_name
        self.dpi = dpi

    def _client(self) -> Any:
        try:
            import boto3
        except ImportError as e:
            raise ImportError(
                "boto3 is required for the Textract parser. "
                "Install with: pip install docuflow[aws]"
            ) from e
        kwargs = {"region_name": self.region_name} if self.region_name else {}
        return boto3.client("textract", **kwargs)

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        from docuflow.rendering.renderer import render_all_pages

        images = await render_all_pages(file_path, dpi=self.dpi)
        client = self._client()
        loop = asyncio.get_event_loop()

        # Textract geometry is relative (0-1); project onto point-space page
        # dims so all bboxes land in the canonical coordinate space.
        scale = 72.0 / self.dpi
        # Bounded parallel page calls — concurrency capped to stay friendly
        # to Textract's per-account rate limits.
        semaphore = asyncio.Semaphore(4)

        async def _process_page(i: int, image) -> Page:
            buf = io.BytesIO()
            # JPEG keeps each page under Textract's 5 MB synchronous API
            # limit; PNG at 200+ DPI can exceed it.
            image.convert("RGB").save(buf, format="JPEG", quality=90)
            async with semaphore:
                response = await loop.run_in_executor(
                    _EXECUTOR, partial(_detect_sync, client, buf.getvalue()),
                )
            return map_textract_response(
                response, i, float(image.width) * scale, float(image.height) * scale,
            )

        pages: list[Page] = list(await asyncio.gather(
            *(_process_page(i, image) for i, image in enumerate(images))
        ))

        document.pages = pages
        document.raw_text = "\n\n".join(p.text for p in pages)
        document.metadata.page_count = len(pages)
        document.status = "parsed"
        return document
