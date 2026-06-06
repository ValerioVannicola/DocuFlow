from __future__ import annotations

from pydantic import BaseModel, Field

from docflow.documents.models import BoundingBox, Document


class SearchHit(BaseModel):
    text: str
    page_number: int
    block_id: str | None = None
    bbox: BoundingBox | None = None
    context: str = ""


class SearchResult(BaseModel):
    query: str
    total_hits: int = 0
    hits: list[SearchHit] = Field(default_factory=list)


def search_document(
    document: Document,
    query: str,
    case_sensitive: bool = False,
    context_chars: int = 50,
) -> SearchResult:
    if not query:
        return SearchResult(query=query)

    hits: list[SearchHit] = []
    q = query if case_sensitive else query.lower()

    for page in document.pages:
        for block in page.blocks:
            text = block.text
            search_text = text if case_sensitive else text.lower()

            start = 0
            while True:
                idx = search_text.find(q, start)
                if idx == -1:
                    break

                ctx_start = max(0, idx - context_chars)
                ctx_end = min(len(text), idx + len(query) + context_chars)
                context = text[ctx_start:ctx_end]
                if ctx_start > 0:
                    context = "..." + context
                if ctx_end < len(text):
                    context = context + "..."

                hits.append(SearchHit(
                    text=text[idx : idx + len(query)],
                    page_number=page.page_number,
                    block_id=block.block_id,
                    bbox=block.bbox,
                    context=context,
                ))
                start = idx + 1

        page_text = page.text
        search_page = page_text if case_sensitive else page_text.lower()
        if q in search_page:
            block_ids = {h.block_id for h in hits if h.page_number == page.page_number}
            if not block_ids:
                idx = search_page.find(q)
                ctx_start = max(0, idx - context_chars)
                ctx_end = min(len(page_text), idx + len(query) + context_chars)
                hits.append(SearchHit(
                    text=page_text[idx : idx + len(query)],
                    page_number=page.page_number,
                    context=page_text[ctx_start:ctx_end],
                ))

    return SearchResult(query=query, total_hits=len(hits), hits=hits)
