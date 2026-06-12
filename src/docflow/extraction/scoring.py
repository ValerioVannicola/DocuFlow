from __future__ import annotations

from docflow.documents.locate import (
    DEFAULT_FUZZY_THRESHOLD,
    _normalize,
    locate_text,
)
from docflow.documents.models import Document, Page
from docflow.extraction.models import (
    FieldConsensus,
    OCRDocumentConfidence,
    OCRFieldConfidence,
)

_LOW_CONFIDENCE_THRESHOLD = 0.6


def compute_document_ocr_confidence(
    document: Document,
) -> OCRDocumentConfidence | None:
    """Aggregate OCR confidence across all blocks of a document.

    Returns None when no block carries a confidence — the signal that no
    OCR ran in the pipeline (e.g. pdfplumber parsing of a native PDF).
    """
    confidences: list[float] = []
    for page in document.pages:
        for block in page.blocks:
            if block.words:
                confidences.extend(
                    w.confidence for w in block.words if w.confidence is not None
                )
            elif block.confidence is not None:
                confidences.append(block.confidence)

    if not confidences:
        return None

    low_count = sum(1 for c in confidences if c < _LOW_CONFIDENCE_THRESHOLD)
    return OCRDocumentConfidence(
        score=round(sum(confidences) / len(confidences), 4),
        word_count=len(confidences),
        low_confidence_ratio=round(low_count / len(confidences), 4),
    )


def _page_mean_confidence(page: Page) -> float | None:
    confs: list[float] = []
    for block in page.blocks:
        if block.words:
            confs.extend(w.confidence for w in block.words if w.confidence is not None)
        elif block.confidence is not None:
            confs.append(block.confidence)
    return sum(confs) / len(confs) if confs else None


def compute_field_ocr_confidence(
    document: Document,
    value: object,
    hint_text: str = "",
    hint_page: int | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> OCRFieldConfidence | None:
    """Match an extracted value back to OCR text and score it.

    Uses the text locator (word-span precision, cross-line and cross-page),
    trying the LLM evidence hint first — it is a verbatim source quote, a
    better anchor than the normalized extracted value. The field score is
    the minimum word confidence of the matched span; `bbox`/`rects` carry
    the exact highlight rectangles. Returns None when the document has no
    OCR confidences at all; match_method="unmatched" when OCR exists but
    the value cannot be located.
    """
    has_ocr = any(
        (b.words and any(w.confidence is not None for w in b.words))
        or b.confidence is not None
        for page in document.pages
        for b in page.blocks
    )
    if not has_ocr:
        return None

    targets: list[str] = []
    if hint_text and _normalize(hint_text):
        targets.append(hint_text)
    if value is not None and _normalize(value) and str(value) not in targets:
        targets.append(str(value))
    if not targets:
        return OCRFieldConfidence()

    for target in targets:
        spans = locate_text(
            document, target,
            hint_page=hint_page, fuzzy_threshold=fuzzy_threshold,
        )
        if not spans:
            continue
        span = spans[0]
        return OCRFieldConfidence(
            score=span.confidence if span.confidence is not None else 0.0,
            match_method="exact_block" if span.method == "exact" else "fuzzy_block",
            match_ratio=span.match_ratio,
            matched_text=span.text,
            page_number=span.page_number,
            bbox=span.bbox,
            rects=span.rects,
        )

    for target in targets:
        normalized = _normalize(target)
        for page in document.pages:
            if normalized in _normalize(page.text):
                page_conf = _page_mean_confidence(page)
                return OCRFieldConfidence(
                    score=round(page_conf, 4) if page_conf is not None else None,
                    match_method="page_text",
                    match_ratio=1.0,
                    matched_text=normalized,
                    page_number=page.page_number,
                )

    return OCRFieldConfidence()


def compute_field_consensus(
    final_value: object,
    field_name: str,
    candidates: list[dict],
    n_instances: int,
) -> FieldConsensus:
    """Agreement of candidate extractions with the final (chosen) value."""
    values: list[str] = []
    for c in candidates:
        data = c.get("data", c)
        if field_name in data:
            values.append(_normalize(data[field_name]))

    if not values:
        return FieldConsensus(n_instances=n_instances, n_succeeded=len(candidates))

    normalized_final = _normalize(final_value)
    n_agree = sum(1 for v in values if v == normalized_final)
    majority_count = max(values.count(v) for v in set(values))

    return FieldConsensus(
        n_instances=n_instances,
        n_succeeded=len(candidates),
        agreement=f"{n_agree}/{len(values)}",
        agreement_ratio=round(n_agree / len(values), 4),
        majority_ratio=round(majority_count / len(values), 4),
    )
