from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from docuflow.documents.models import Block, BlockType, BoundingBox, Document, Page, Word
from docuflow.documents.tables import Cell, Table
from docuflow.errors import ParsingError

_EXECUTOR = ThreadPoolExecutor(max_workers=2)

_LABEL_TO_BLOCK_TYPE = {
    "title": BlockType.TITLE,
    "section_header": BlockType.TITLE,
    "text": BlockType.TEXT,
    "paragraph": BlockType.PARAGRAPH,
    "list_item": BlockType.LIST_ITEM,
    "picture": BlockType.IMAGE,
    "chart": BlockType.IMAGE,
    "formula": BlockType.FORMULA,
    "page_header": BlockType.HEADER,
    "page_footer": BlockType.FOOTER,
    "caption": BlockType.TEXT,
    "footnote": BlockType.TEXT,
    "code": BlockType.TEXT,
    "reference": BlockType.TEXT,
}


def _convert_bbox(docling_bbox: Any, page_height: float) -> BoundingBox:
    coord_origin = getattr(docling_bbox, "coord_origin", "TOPLEFT")
    left, top = docling_bbox.l, docling_bbox.t
    right, bottom = docling_bbox.r, docling_bbox.b

    if str(coord_origin) == "BOTTOMLEFT":
        return BoundingBox(x0=left, y0=page_height - bottom, x1=right, y1=page_height - top)
    return BoundingBox(x0=left, y0=top, x1=right, y1=bottom)


def _resolve_headers(table_data: Any) -> dict[int, dict[str, list[str]]]:
    """Build a mapping of (row, col) -> {"row_headers": [...], "col_headers": [...]}."""
    col_header_texts: dict[int, list[str]] = {}
    row_header_texts: dict[int, list[str]] = {}

    for cell in table_data.table_cells:
        if getattr(cell, "column_header", False):
            for c in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                col_header_texts.setdefault(c, []).append(cell.text.strip())
        if getattr(cell, "row_header", False):
            for r in range(cell.start_row_offset_idx, cell.end_row_offset_idx):
                row_header_texts.setdefault(r, []).append(cell.text.strip())

    result: dict[int, dict[str, list[str]]] = {}
    for cell in table_data.table_cells:
        if getattr(cell, "column_header", False):
            continue
        r = cell.start_row_offset_idx
        c = cell.start_col_offset_idx
        key = r * 10000 + c
        result[key] = {
            "col_headers": col_header_texts.get(c, []),
            "row_headers": row_header_texts.get(r, []),
        }
    return result


def _extract_table(item: Any, page_no: int, page_height: float) -> Table | None:
    table_data = getattr(item, "data", None)
    if table_data is None:
        return None

    table_cells_raw = getattr(table_data, "table_cells", [])
    if not table_cells_raw:
        return None

    header_map = _resolve_headers(table_data)

    cells: list[Cell] = []
    for tc in table_cells_raw:
        r = tc.start_row_offset_idx
        c = tc.start_col_offset_idx
        key = r * 10000 + c
        headers = header_map.get(key, {"col_headers": [], "row_headers": []})

        cell_bbox = None
        if tc.bbox:
            cell_bbox = _convert_bbox(tc.bbox, page_height)

        cells.append(Cell(
            row=r,
            col=c,
            row_span=tc.row_span,
            col_span=tc.col_span,
            text=tc.text.strip(),
            is_column_header=getattr(tc, "column_header", False),
            is_row_header=getattr(tc, "row_header", False),
            is_row_section=getattr(tc, "row_section", False),
            row_headers=headers["row_headers"],
            col_headers=headers["col_headers"],
            bbox=cell_bbox,
        ))

    table_bbox = None
    prov = getattr(item, "prov", None)
    if prov and len(prov) > 0 and prov[0].bbox:
        table_bbox = _convert_bbox(prov[0].bbox, page_height)

    markdown = ""
    if hasattr(item, "export_to_markdown"):
        markdown = item.export_to_markdown() or ""

    return Table(
        num_rows=getattr(table_data, "num_rows", 0),
        num_cols=getattr(table_data, "num_cols", 0),
        cells=cells,
        page_number=page_no,
        bbox=table_bbox,
        markdown=markdown.strip(),
    )


def _cell_to_word(cell: Any, page_height: float) -> Word | None:
    """Convert a Docling page cell to a Word — only for cells produced by OCR.

    Native PDF text cells carry no meaningful confidence (they come from the
    text layer), so they are skipped: a native Docling parse keeps reporting
    no OCR confidence. Tolerates both cell API generations (bbox/OcrCell and
    rect/from_ocr).
    """
    from_ocr = getattr(cell, "from_ocr", None)
    if from_ocr is None:
        from_ocr = type(cell).__name__ == "OcrCell"
    if not from_ocr:
        return None

    confidence = getattr(cell, "confidence", None)
    if confidence is None:
        return None

    text = (getattr(cell, "text", "") or "").strip()
    if not text:
        return None

    raw_bbox = getattr(cell, "bbox", None)
    if raw_bbox is None:
        rect = getattr(cell, "rect", None)
        if rect is not None and hasattr(rect, "to_bounding_box"):
            raw_bbox = rect.to_bounding_box()

    bbox = None
    if raw_bbox is not None:
        try:
            bbox = _convert_bbox(raw_bbox, page_height)
        except Exception:
            bbox = None

    return Word(text=text, bbox=bbox, confidence=float(confidence))


def _harvest_ocr_words(
    result: Any,
    page_numbers: list[int],
    page_dimensions: dict[int, tuple[float, float]],
) -> dict[int, list[Word]]:
    """Collect OCR word confidences from ConversionResult.pages.

    The document model (result.document) carries no confidences; they only
    exist on the page model cells. Pages are matched positionally to the
    document page numbers.
    """
    conv_pages = list(getattr(result, "pages", None) or [])
    if len(conv_pages) != len(page_numbers):
        return {}

    words: dict[int, list[Word]] = {}
    for page_no, conv_page in zip(page_numbers, conv_pages, strict=True):
        cells = getattr(conv_page, "cells", None) or []
        _w, h = page_dimensions.get(page_no, (595.0, 842.0))
        page_words = [
            word for c in cells if (word := _cell_to_word(c, h)) is not None
        ]
        if page_words:
            words[page_no] = page_words
    return words


def _attach_words_to_blocks(blocks: list[Block], words: list[Word]) -> list[Block]:
    """Assign OCR words to layout blocks by bbox-center containment."""
    if not words:
        return blocks

    leftover = [w for w in words if w.bbox is not None]
    out: list[Block] = []
    for block in blocks:
        if block.bbox is None or block.block_type == BlockType.IMAGE:
            out.append(block)
            continue

        mine: list[Word] = []
        rest: list[Word] = []
        for word in leftover:
            cx = (word.bbox.x0 + word.bbox.x1) / 2
            cy = (word.bbox.y0 + word.bbox.y1) / 2
            if block.bbox.x0 <= cx <= block.bbox.x1 and block.bbox.y0 <= cy <= block.bbox.y1:
                mine.append(word)
            else:
                rest.append(word)
        leftover = rest

        if mine:
            confs = [w.confidence for w in mine if w.confidence is not None]
            out.append(
                block.model_copy(
                    update={
                        "words": mine,
                        "confidence": sum(confs) / len(confs) if confs else None,
                    }
                )
            )
        else:
            out.append(block)
    return out


def _parse_with_docling(file_path: str) -> dict:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise ImportError(
            "docling is required for Docling parsing. "
            "Install with: pip install docuflow[docling]"
        ) from e

    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
    except Exception as exc:
        raise ParsingError(f"Docling failed to convert: {file_path}") from exc

    doc = result.document

    page_dimensions: dict[int, tuple[float, float]] = {}
    for page_no, page_obj in doc.pages.items():
        w = page_obj.size.width if page_obj.size else 595.0
        h = page_obj.size.height if page_obj.size else 842.0
        page_dimensions[page_no] = (w, h)

    page_blocks: dict[int, list[Block]] = {}
    page_tables: dict[int, list[Table]] = {}
    page_texts: dict[int, list[str]] = {}

    for item, _level in doc.iterate_items():
        label_str = item.label.value if hasattr(item.label, "value") else str(item.label)

        page_no = 0
        if hasattr(item, "prov") and item.prov:
            prov = item.prov[0]
            page_no = prov.page_no if prov.page_no is not None else 0

        _w, h = page_dimensions.get(page_no, (595.0, 842.0))

        if label_str == "table":
            table = _extract_table(item, page_no, h)
            if table is not None:
                page_tables.setdefault(page_no, []).append(table)
                page_texts.setdefault(page_no, []).append(table.markdown)
            continue

        block_type = _LABEL_TO_BLOCK_TYPE.get(label_str, BlockType.TEXT)

        text = ""
        if hasattr(item, "text"):
            text = item.text or ""
        elif hasattr(item, "export_to_markdown"):
            text = item.export_to_markdown() or ""

        if not text.strip() and block_type != BlockType.IMAGE:
            continue

        bbox = None
        if hasattr(item, "prov") and item.prov and item.prov[0].bbox:
            bbox = _convert_bbox(item.prov[0].bbox, h)

        block = Block(
            block_id=str(uuid.uuid4()),
            block_type=block_type,
            text=text.strip(),
            bbox=bbox,
        )

        page_blocks.setdefault(page_no, []).append(block)
        page_texts.setdefault(page_no, []).append(text.strip())

    sorted_page_numbers = sorted(page_dimensions.keys())
    try:
        ocr_words = _harvest_ocr_words(result, sorted_page_numbers, page_dimensions)
    except Exception:
        ocr_words = {}

    pages: list[dict] = []
    for page_no in sorted_page_numbers:
        w, h = page_dimensions[page_no]
        pages.append({
            "page_number": page_no,
            "width": w,
            "height": h,
            "blocks": _attach_words_to_blocks(
                page_blocks.get(page_no, []), ocr_words.get(page_no, []),
            ),
            "tables": page_tables.get(page_no, []),
            "text": "\n".join(page_texts.get(page_no, [])),
        })

    markdown = doc.export_to_markdown()

    return {"pages": pages, "markdown": markdown}


class DoclingParser:
    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _EXECUTOR, partial(_parse_with_docling, file_path),
        )

        pages = [
            Page(
                page_number=p["page_number"],
                width=p["width"],
                height=p["height"],
                blocks=p["blocks"],
                tables=p["tables"],
                text=p["text"],
            )
            for p in result["pages"]
        ]

        document.pages = pages
        document.raw_text = result["markdown"]
        document.metadata.page_count = len(pages)
        document.status = "parsed"
        return document
