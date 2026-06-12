from __future__ import annotations

from difflib import SequenceMatcher
from itertools import pairwise
from typing import NamedTuple

from pydantic import BaseModel, Field

from docuflow.documents.models import BlockType, BoundingBox, Document, PageRect

DEFAULT_FUZZY_THRESHOLD = 0.8

# Words on the same line whose horizontal gap is below this fraction of the
# word height join without a space (dash-split tokens, tight kerning).
_NO_SPACE_GAP_RATIO = 0.3


class TextSpan(BaseModel):
    """A located piece of text: where a phrase lives in the document.

    `rects` holds one rectangle per (page, line) segment — a span crossing
    lines or pages produces multiple rects, like a PDF viewer selection.
    `bbox` is the union rect when the span sits on a single page, None when
    it crosses pages. `confidence` is the minimum word confidence of the
    matched span (None when no OCR confidences exist).
    """

    text: str
    page_number: int
    bbox: BoundingBox | None = None
    rects: list[PageRect] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    match_ratio: float = 1.0
    method: str = "exact"  # "exact" | "fuzzy"
    confidence: float | None = None


class _StreamWord(NamedTuple):
    text: str
    norm: str
    bbox: BoundingBox | None
    confidence: float | None
    block_id: str
    page_number: int


def _normalize(value: object, case_sensitive: bool = False) -> str:
    s = str(value).strip()
    if not case_sensitive:
        s = s.lower()
    for ch in "$€£¥,":
        s = s.replace(ch, "")
    return " ".join(s.split())


def build_stream(document: Document, case_sensitive: bool = False) -> list[_StreamWord]:
    """Prebuild the locator word stream for repeated locate_text calls."""
    return _build_stream(document, case_sensitive)


def _build_stream(document: Document, case_sensitive: bool) -> list[_StreamWord]:
    """Flatten the document into one word stream, crossing block and page
    boundaries. Blocks without word detail contribute whitespace-split tokens
    that share the block's bbox and confidence."""
    stream: list[_StreamWord] = []
    for page in document.pages:
        for block in page.blocks:
            if block.block_type == BlockType.IMAGE:
                continue
            if block.words:
                for word in block.words:
                    norm = _normalize(word.text, case_sensitive)
                    if norm:
                        stream.append(_StreamWord(
                            word.text, norm, word.bbox, word.confidence,
                            block.block_id, page.page_number,
                        ))
            else:
                for token in block.text.split():
                    norm = _normalize(token, case_sensitive)
                    if norm:
                        stream.append(_StreamWord(
                            token, norm, block.bbox, block.confidence,
                            block.block_id, page.page_number,
                        ))
    return stream


def _joined(window: list[_StreamWord], tight: bool) -> str:
    """Join window words with inferred separators.

    `tight=False` joins with spaces. `tight=True` applies LiteParse-style
    separator inference: adjacent words in the same block whose horizontal
    gap is small relative to the word height join without a space.
    """
    if not tight:
        return " ".join(w.norm for w in window)

    parts = [window[0].norm]
    for prev, cur in pairwise(window):
        sep = " "
        if (
            prev.block_id == cur.block_id
            and prev.bbox is not None
            and cur.bbox is not None
            and prev.bbox is not cur.bbox
        ):
            height = max(prev.bbox.height, cur.bbox.height)
            gap = cur.bbox.x0 - prev.bbox.x1
            if height > 0 and gap <= height * _NO_SPACE_GAP_RATIO:
                sep = ""
        parts.append(sep + cur.norm)
    return "".join(parts)


def _exact_contains(window: list[_StreamWord], query: str) -> bool:
    spaced = _joined(window, tight=False)
    if query == spaced or query in spaced:
        return True
    tight = _joined(window, tight=True)
    return tight != spaced and (query == tight or query in tight)


def _narrow_window(window: list[_StreamWord], query: str) -> list[_StreamWord]:
    """Shrink an exact-matching window from both edges while it still matches,
    so the span covers only the words that are part of the match."""
    while len(window) > 1 and _exact_contains(window[1:], query):
        window = window[1:]
    while len(window) > 1 and _exact_contains(window[:-1], query):
        window = window[:-1]
    return window


def _window_match(window: list[_StreamWord], query: str) -> float | None:
    """Match ratio of query against a window: 1.0 exact, <1.0 fuzzy, None poor."""
    spaced = _joined(window, tight=False)
    if not spaced:
        return None
    if _exact_contains(window, query):
        return 1.0

    matcher = SequenceMatcher(None, query, spaced)
    if matcher.quick_ratio() < 0.5:
        return None
    return matcher.ratio()


def _span_from_window(
    window: list[_StreamWord], ratio: float,
) -> TextSpan:
    rects: list[PageRect] = []
    current: tuple[int, str] | None = None
    group: list[BoundingBox] = []

    def flush_group() -> None:
        if group and current is not None:
            rects.append(PageRect(
                page_number=current[0],
                bbox=BoundingBox(
                    x0=min(b.x0 for b in group),
                    y0=min(b.y0 for b in group),
                    x1=max(b.x1 for b in group),
                    y1=max(b.y1 for b in group),
                ),
            ))

    for w in window:
        key = (w.page_number, w.block_id)
        if key != current:
            flush_group()
            current = key
            group = []
        if w.bbox is not None and w.bbox not in group:
            group.append(w.bbox)
    flush_group()

    pages = {w.page_number for w in window}
    bbox = None
    if len(pages) == 1 and rects:
        bbox = BoundingBox(
            x0=min(r.bbox.x0 for r in rects),
            y0=min(r.bbox.y0 for r in rects),
            x1=max(r.bbox.x1 for r in rects),
            y1=max(r.bbox.y1 for r in rects),
        )

    confs = [w.confidence for w in window if w.confidence is not None]
    block_ids: list[str] = []
    for w in window:
        if w.block_id not in block_ids:
            block_ids.append(w.block_id)

    return TextSpan(
        text=" ".join(w.text for w in window),
        page_number=window[0].page_number,
        bbox=bbox,
        rects=rects,
        block_ids=block_ids,
        match_ratio=round(ratio, 4),
        method="exact" if ratio == 1.0 else "fuzzy",
        confidence=round(min(confs), 4) if confs else None,
    )


def locate_text(
    document: Document,
    query: str,
    *,
    case_sensitive: bool = False,
    fuzzy: bool = True,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    hint_page: int | None = None,
    find_all: bool = False,
    stream: list[_StreamWord] | None = None,
) -> list[TextSpan]:
    """Locate a phrase in the document and return precise highlight spans.

    Matching is normalization-aware (case, currency symbols, whitespace),
    works across word, line and page boundaries, and falls back to fuzzy
    matching (SequenceMatcher) for OCR-garbled text when `fuzzy` is on.

    Returns spans ordered best-first. With `find_all=False` only the single
    best span is returned (exact preferred over fuzzy; `hint_page` matches
    preferred over the rest). With `find_all=True` every non-overlapping
    exact match is returned in document order.
    """
    q = _normalize(query, case_sensitive)
    if not q:
        return []

    # Callers locating many phrases in one document can prebuild the word
    # stream once via build_stream() and pass it in.
    if stream is None:
        stream = _build_stream(document, case_sensitive)
    if not stream:
        return []

    n_tokens = max(1, len(q.split()))
    window_sizes = [n_tokens]
    if n_tokens > 1:
        window_sizes.append(n_tokens - 1)
    window_sizes.append(min(len(stream), n_tokens + 1))

    exact: list[tuple[int, TextSpan]] = []
    best_fuzzy: tuple[float, int, TextSpan] | None = None

    start = 0
    while start < len(stream):
        matched_end: int | None = None
        for size in window_sizes:
            if size < 1 or start + size > len(stream):
                continue
            window = stream[start : start + size]
            ratio = _window_match(window, q)
            if ratio is None:
                continue
            if ratio == 1.0:
                narrowed = _narrow_window(window, q)
                exact.append((start, _span_from_window(narrowed, ratio)))
                matched_end = start + size
                break
            if (
                fuzzy
                and ratio >= fuzzy_threshold
                and (best_fuzzy is None or ratio > best_fuzzy[0])
            ):
                best_fuzzy = (ratio, start, _span_from_window(window, ratio))

        if matched_end is not None:
            # Stop early only when no better-ranked match could follow:
            # with a hint page, keep scanning until a match lands on it.
            if not find_all and (
                hint_page is None or exact[-1][1].page_number == hint_page
            ):
                break
            start = matched_end
        else:
            start += 1

    def hint_rank(item: tuple[int, TextSpan]) -> tuple[int, int]:
        _, span = item
        on_hint = 0 if hint_page is not None and span.page_number == hint_page else 1
        return (on_hint, item[0])

    if exact:
        if find_all:
            return [span for _, span in exact]
        return [min(exact, key=hint_rank)[1]]

    if best_fuzzy is not None:
        return [best_fuzzy[2]]

    return []
