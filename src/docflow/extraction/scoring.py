from __future__ import annotations

from difflib import SequenceMatcher

from docflow.documents.models import Block, Document, Page
from docflow.extraction.models import (
    FieldConsensus,
    OCRDocumentConfidence,
    OCRFieldConfidence,
)

_LOW_CONFIDENCE_THRESHOLD = 0.6
DEFAULT_FUZZY_THRESHOLD = 0.8


def _normalize(value: object) -> str:
    s = str(value).strip().lower()
    for ch in "$€£¥,":
        s = s.replace(ch, "")
    return " ".join(s.split())


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


def _word_span_score(block: Block, target: str) -> tuple[float, float, str] | None:
    """Best (match_ratio, score, matched_text) for target within a block.

    Slides a window of consecutive words sized to the target's token count
    (±1) and compares normalized text. The span score is the minimum word
    confidence in the window.
    """
    if not block.words:
        normalized_block = _normalize(block.text)
        if not normalized_block:
            return None
        if target in normalized_block:
            ratio = 1.0
        else:
            matcher = SequenceMatcher(None, target, normalized_block)
            if matcher.quick_ratio() < 0.5:
                return None
            ratio = matcher.ratio()
        score = block.confidence if block.confidence is not None else 0.0
        return (ratio, score, block.text)

    n_target = max(1, len(target.split()))
    words = block.words
    best: tuple[float, float, str] | None = None

    for size in {max(1, n_target - 1), n_target, min(len(words), n_target + 1)}:
        if size > len(words):
            continue
        for start in range(len(words) - size + 1):
            span = words[start : start + size]
            span_text = " ".join(w.text for w in span)
            normalized_span = _normalize(span_text)
            if not normalized_span:
                continue

            if normalized_span == target or target in normalized_span:
                ratio = 1.0
            else:
                matcher = SequenceMatcher(None, target, normalized_span)
                if matcher.quick_ratio() < 0.5:
                    continue
                ratio = matcher.ratio()

            confs = [w.confidence for w in span if w.confidence is not None]
            score = min(confs) if confs else 0.0
            if best is None or ratio > best[0] or (ratio == best[0] and score > best[1]):
                best = (ratio, score, span_text)

    return best


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

    Tries the LLM evidence hint first (it is a verbatim source quote, a
    better anchor than the normalized extracted value), searching the hinted
    page before the rest. Returns None when the document has no OCR
    confidences at all; returns match_method="unmatched" when OCR exists but
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

    targets = []
    if hint_text:
        normalized_hint = _normalize(hint_text)
        if normalized_hint:
            targets.append(normalized_hint)
    if value is not None:
        normalized_value = _normalize(value)
        if normalized_value and normalized_value not in targets:
            targets.append(normalized_value)
    if not targets:
        return OCRFieldConfidence()

    pages = sorted(
        document.pages,
        key=lambda p: 0 if hint_page is not None and p.page_number == hint_page else 1,
    )

    best: OCRFieldConfidence | None = None
    for target in targets:
        for page in pages:
            for block in page.blocks:
                span = _word_span_score(block, target)
                if span is None:
                    continue
                ratio, score, matched_text = span
                if ratio < fuzzy_threshold:
                    continue
                candidate = OCRFieldConfidence(
                    score=round(score, 4),
                    match_method="exact_block" if ratio == 1.0 else "fuzzy_block",
                    match_ratio=round(ratio, 4),
                    matched_text=matched_text,
                    page_number=page.page_number,
                )
                if best is None or candidate.match_ratio > best.match_ratio:
                    best = candidate
            if best is not None and best.match_ratio == 1.0:
                return best
        if best is not None:
            return best

    for target in targets:
        for page in pages:
            if target in _normalize(page.text):
                page_conf = _page_mean_confidence(page)
                return OCRFieldConfidence(
                    score=round(page_conf, 4) if page_conf is not None else None,
                    match_method="page_text",
                    match_ratio=1.0,
                    matched_text=target,
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
