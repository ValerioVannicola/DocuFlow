from __future__ import annotations

from docflow.documents.evidence import Evidence
from docflow.documents.models import Document


def attach_evidence(
    document: Document,
    field_name: str,
    extracted_value: object,
    evidence_hints: dict,
) -> list[Evidence]:
    """Map LLM evidence hints to Evidence objects grounded in the document.

    Searches ALL pages for the evidence text rather than trusting the
    LLM-reported page number. Falls back to the LLM hint if no match found.
    """
    evidences: list[Evidence] = []

    hint_page = evidence_hints.get("page", 0) if evidence_hints else 0
    text_snippet = evidence_hints.get("text", "") if evidence_hints else ""

    if not text_snippet and extracted_value is not None:
        text_snippet = str(extracted_value)

    if not text_snippet:
        return evidences

    matched_page = None
    matched_block_id = None
    matched_bbox = None
    confidence = None

    for page in document.pages:
        for block in page.blocks:
            if text_snippet in block.text:
                matched_page = page.page_number
                matched_block_id = block.block_id
                matched_bbox = block.bbox
                confidence = block.confidence
                break
        if matched_block_id is not None:
            break

    if matched_block_id is None:
        for page in document.pages:
            if text_snippet in page.text:
                matched_page = page.page_number
                confidence = 0.7
                break

    if matched_page is None:
        matched_page = hint_page

    evidences.append(
        Evidence(
            document_id=document.id,
            page_number=matched_page,
            text=text_snippet,
            bbox=matched_bbox,
            block_id=matched_block_id,
            confidence=confidence,
        )
    )

    return evidences
