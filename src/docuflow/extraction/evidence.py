from __future__ import annotations

from docuflow.documents.evidence import Evidence
from docuflow.documents.locate import _normalize, locate_text
from docuflow.documents.models import Document


def attach_evidence(
    document: Document,
    field_name: str,
    extracted_value: object,
    evidence_hints: dict,
    stream: list | None = None,
) -> list[Evidence]:
    """Map LLM evidence hints to Evidence objects grounded in the document.

    Locates the evidence text (hint quote first, extracted value second) at
    word-span precision via the text locator: the bbox covers exactly the
    matched words, and `rects` carries one rectangle per line — including
    spans that cross line or page boundaries. Falls back to a page-level
    match (no bbox), then to the LLM-reported page.

    Composite values (lists and nested objects) are decomposed into their leaf
    strings, and each leaf is grounded independently — so a ``List[str]`` or a
    ``List[SomeModel]`` field gets one box per locatable item instead of a
    single unsearchable Python ``repr`` (e.g. ``"[{'code': ...}]"``).
    """
    hint_page = evidence_hints.get("page", 0) if evidence_hints else 0
    hint_text = evidence_hints.get("text", "") if evidence_hints else ""

    # Composite values: ground each leaf string separately so list/nested-object
    # fields produce one box per locatable piece. Falls through to the scalar
    # path below when nothing could be located.
    if isinstance(extracted_value, (list, tuple, dict)):
        evidences: list[Evidence] = []
        seen: set[str] = set()
        for target in _leaf_strings(extracted_value):
            if target in seen:
                continue
            seen.add(target)
            spans = locate_text(document, target, hint_page=hint_page, stream=stream)
            if not spans:
                continue
            span = spans[0]
            if span.bbox is None and not span.rects:
                continue
            evidences.append(Evidence(
                document_id=document.id,
                page_number=span.page_number,
                text=target,
                bbox=span.bbox,
                rects=span.rects,
                block_id=span.block_ids[0] if span.block_ids else None,
                confidence=span.confidence,
            ))
        if evidences:
            return evidences
        # Nothing located: fall back to the hint text / page below.

    text_snippet = hint_text
    if not text_snippet and extracted_value is not None:
        text_snippet = str(extracted_value)

    if not text_snippet:
        return []

    targets = [text_snippet]
    if extracted_value is not None and str(extracted_value) != text_snippet:
        targets.append(str(extracted_value))

    best_span = None
    for target in targets:
        spans = locate_text(document, target, hint_page=hint_page, stream=stream)
        if not spans:
            continue
        if spans[0].method == "exact":
            best_span = spans[0]
            break
        if best_span is None:
            best_span = spans[0]
    if best_span is not None:
        span = best_span
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


def _leaf_strings(value: object) -> list[str]:
    """Flatten a value into its locatable leaf strings, in document-ish order.

    Lists/tuples/sets are expanded element-wise; dicts (nested Pydantic objects
    dumped to plain data) contribute their values. Booleans and ``None`` are
    skipped — ``"True"``/``"False"`` are not text that appears in the document.
    """
    out: list[str] = []

    def walk(v: object) -> None:
        if v is None or isinstance(v, bool):
            return
        if isinstance(v, dict):
            for sub in v.values():
                walk(sub)
        elif isinstance(v, (list, tuple, set)):
            for sub in v:
                walk(sub)
        else:
            s = str(v).strip()
            if s:
                out.append(s)

    walk(value)
    return out
