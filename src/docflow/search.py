from __future__ import annotations

from pydantic import BaseModel, Field

from docflow.documents.locate import locate_text
from docflow.documents.models import BoundingBox, Document, PageRect


class SearchHit(BaseModel):
    text: str
    page_number: int
    block_id: str | None = None
    bbox: BoundingBox | None = None
    rects: list[PageRect] = Field(default_factory=list)
    match_ratio: float = 1.0
    context: str = ""


class SearchResult(BaseModel):
    query: str
    total_hits: int = 0
    hits: list[SearchHit] = Field(default_factory=list)


def _context_for(document: Document, page_number: int, matched_text: str, context_chars: int) -> str:
    for page in document.pages:
        if page.page_number != page_number:
            continue
        idx = page.text.lower().find(matched_text.lower())
        if idx == -1:
            return matched_text
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(page.text), idx + len(matched_text) + context_chars)
        context = page.text[ctx_start:ctx_end]
        if ctx_start > 0:
            context = "..." + context
        if ctx_end < len(page.text):
            context = context + "..."
        return context
    return matched_text


def search_document(
    document: Document,
    query: str,
    case_sensitive: bool = False,
    context_chars: int = 50,
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.8,
) -> SearchResult:
    """Search the document for a phrase, returning word-precise highlight rects.

    Matches can span word, line and page boundaries; each hit carries the
    union `bbox` (single-page matches) and per-line `rects` for rendering
    multi-line/multi-page highlights. With `fuzzy=True`, OCR-garbled text
    matches approximately (best match only, with its `match_ratio`).
    """
    if not query:
        return SearchResult(query=query)

    spans = locate_text(
        document,
        query,
        case_sensitive=case_sensitive,
        fuzzy=False,
        find_all=True,
    )

    if not spans and fuzzy:
        spans = locate_text(
            document,
            query,
            case_sensitive=case_sensitive,
            fuzzy=True,
            fuzzy_threshold=fuzzy_threshold,
        )

    hits = [
        SearchHit(
            text=span.text,
            page_number=span.page_number,
            block_id=span.block_ids[0] if span.block_ids else None,
            bbox=span.bbox,
            rects=span.rects,
            match_ratio=span.match_ratio,
            context=_context_for(document, span.page_number, span.text, context_chars),
        )
        for span in spans
    ]

    # Page-text fallback for pages whose text isn't represented in blocks
    normalized_q = query if case_sensitive else query.lower()
    matched_pages = {h.page_number for h in hits}
    for page in document.pages:
        if page.page_number in matched_pages:
            continue
        page_text = page.text if case_sensitive else page.text.lower()
        idx = page_text.find(normalized_q)
        if idx != -1:
            hits.append(
                SearchHit(
                    text=page.text[idx : idx + len(query)],
                    page_number=page.page_number,
                    context=_context_for(document, page.page_number, query, context_chars),
                )
            )

    return SearchResult(query=query, total_hits=len(hits), hits=hits)
