from __future__ import annotations

from docflow.documents.evidence import Evidence
from docflow.documents.locate import _normalize, locate_text
from docflow.documents.models import Document


def attach_evidence(
    document: Document,
    field_name: str,
    extracted_value: object,
    evidence_hints: dict,
) -> list[Evidence]:
    """Map LLM evidence hints to Evidence objects grounded in the document.

    Locates the evidence text (hint quote first, extracted value second) at
    word-span precision via the text locator: the bbox covers exactly the
    matched words, and `rects` carries one rectangle per line — including
    spans that cross line or page boundaries. Falls back to a page-level
    match (no bbox), then to the LLM-reported page.
    """
    hint_page = evidence_hints.get("page", 0) if evidence_hints else 0
    text_snippet = evidence_hints.get("text", "") if evidence_hints else ""

    if not text_snippet and extracted_value is not None:
        text_snippet = str(extracted_value)

    if not text_snippet:
        return []

    targets = [text_snippet]
    if extracted_value is not None and str(extracted_value) != text_snippet:
        targets.append(str(extracted_value))

    for target in targets:
        spans = locate_text(document, target, hint_page=hint_page)
        if spans:
            span = spans[0]
            return [
                Evidence(
                    document_id=document.id,
                    page_number=span.page_number,
                    text=text_snippet,
                    bbox=span.bbox,
                    rects=span.rects,
                    block_id=span.block_ids[0] if span.block_ids else None,
                    confidence=span.confidence,
                )
            ]

    # Page-level fallback: text exists in the page text but not in any block
    # (e.g. tables serialized to page text only).
    normalized_snippet = _normalize(text_snippet)
    for page in document.pages:
        if normalized_snippet and normalized_snippet in _normalize(page.text):
            return [
                Evidence(
                    document_id=document.id,
                    page_number=page.page_number,
                    text=text_snippet,
                    confidence=0.7,
                )
            ]

    return [
        Evidence(
            document_id=document.id,
            page_number=hint_page,
            text=text_snippet,
        )
    ]
