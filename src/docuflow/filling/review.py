"""Heuristics that decide whether a planned PDF fill should be reviewed by a human.

Filling review is opt-in (``review=True`` on ``fill_pdf_form``). When enabled,
these checks populate ``FillingResult.review_reasons`` and ``needs_review`` so a
reviewer can correct values/placements before the PDF is committed.
"""

from __future__ import annotations

from docuflow.filling.models import FillingResult

# Methods that place values without an exact, declared target — inherently uncertain.
_AUTO_METHODS = {"auto_detected_blank", "llm_detected_blank"}


def evaluate_fill_review(
    result: FillingResult,
    *,
    min_confidence: float = 0.6,
    flag_auto_detected: bool = True,
) -> list[str]:
    """Return human-readable reasons the fill should be reviewed (empty = clean)."""
    reasons: list[str] = []

    for name, field in result.fields.items():
        placement = field.placement
        if (
            placement is not None
            and placement.confidence is not None
            and placement.confidence < min_confidence
        ):
            reasons.append(
                f"Field '{name}' placement confidence {placement.confidence:.2f} "
                f"is below {min_confidence:.2f}."
            )
        if flag_auto_detected and field.method in _AUTO_METHODS:
            reasons.append(
                f"Field '{name}' was located by automatic blank detection "
                f"({field.method}); verify the placement."
            )
        for warning in field.warnings:
            reasons.append(f"Field '{name}': {warning}")

    if result.unmapped_model_fields:
        reasons.append(
            "Some data fields could not be placed: "
            + ", ".join(result.unmapped_model_fields)
        )

    return reasons
