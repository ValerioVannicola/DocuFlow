from __future__ import annotations

from pydantic import BaseModel

from docuflow.documents.models import Document
from docuflow.extraction.scoring import compute_document_ocr_confidence


class EscalationPolicy(BaseModel):
    """Thresholds deciding when OCR output is too poor to trust and the
    document should be re-read by a vision LLM instead.

    Defaults are conservative starting points, not laws — tune them against
    your real documents.
    """

    min_ocr_score: float = 0.6
    max_low_confidence_ratio: float = 0.4
    min_chars_per_page: int = 20
    escalate_to: str = "vision"  # "vision" | "hybrid"


def evaluate_escalation(
    document: Document, policy: EscalationPolicy | None = None,
) -> tuple[bool, str]:
    """Decide whether a parsed document's text is too unreliable for text
    extraction. Returns (escalate, reason).

    Signals, in order:
    - OCR ran and its confidence is poor (low mean score, or too many
      low-confidence words) — OCR "succeeded" but produced garbage.
    - No usable text at all — neither the native text layer nor OCR
      yielded enough characters to extract from.
    """
    policy = policy or EscalationPolicy()

    n_pages = max(1, len(document.pages))
    total_chars = len(document.raw_text.strip())
    if total_chars < policy.min_chars_per_page * n_pages:
        return True, (
            f"document has {total_chars} chars across {n_pages} page(s), "
            f"below {policy.min_chars_per_page}/page — no usable text"
        )

    doc_ocr = compute_document_ocr_confidence(document)
    if doc_ocr is None:
        # Pure native text layer with substance: nothing was mis-read.
        return False, "native text layer, no OCR ran"

    if doc_ocr.score < policy.min_ocr_score:
        return True, (
            f"OCR confidence {doc_ocr.score:.2f} below "
            f"threshold {policy.min_ocr_score}"
        )
    if doc_ocr.low_confidence_ratio > policy.max_low_confidence_ratio:
        return True, (
            f"{doc_ocr.low_confidence_ratio:.0%} of OCR words below confidence 0.6 "
            f"(threshold {policy.max_low_confidence_ratio:.0%})"
        )

    return False, f"OCR confidence {doc_ocr.score:.2f} acceptable"
