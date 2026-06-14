from __future__ import annotations

from typing import Protocol, runtime_checkable

from docuflow.extraction.models import ExtractionResult


@runtime_checkable
class ReviewRule(Protocol):
    def check(self, result: ExtractionResult) -> str | None:
        """Return a reason string if review is needed, None if it passes."""
        ...


class OverallConfidenceBelow:
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def check(self, result: ExtractionResult) -> str | None:
        if result.confidence < self.threshold:
            return (
                f"Overall confidence {result.confidence:.2f} "
                f"is below threshold {self.threshold}"
            )
        return None


class FieldConfidenceBelow:
    def __init__(self, fields: dict[str, float]):
        self.fields = fields

    def check(self, result: ExtractionResult) -> str | None:
        reasons = []
        for field_name, threshold in self.fields.items():
            if field_name in result.fields:
                field = result.fields[field_name]
                gate = field.trust.trust_gate if field.trust else False
                if threshold > 0 and not gate:
                    reasons.append(
                        f"Field '{field_name}' trust gate is false"
                    )
        return "; ".join(reasons) if reasons else None


class AnyFieldConfidenceBelow:
    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    def check(self, result: ExtractionResult) -> str | None:
        for field_name, field in result.fields.items():
            gate = field.trust.trust_gate if field.trust else False
            if not gate:
                return (
                    f"Field '{field_name}' trust gate is false"
                )
        return None


class HasValidationErrors:
    def check(self, result: ExtractionResult) -> str | None:
        error_count = len(result.validation_errors)
        if error_count > 0:
            return f"Document has {error_count} validation error(s)"
        return None


class FieldMissing:
    def __init__(self, fields: list[str]):
        self.fields = fields

    def check(self, result: ExtractionResult) -> str | None:
        missing = []
        for field_name in self.fields:
            if field_name not in result.fields or result.fields[field_name].value is None:
                missing.append(field_name)
        if missing:
            return f"Critical field(s) missing: {', '.join(missing)}"
        return None


class NoEvidence:
    def __init__(self, fields: list[str] | None = None):
        self.fields = fields

    def check(self, result: ExtractionResult) -> str | None:
        check_fields = self.fields or list(result.fields.keys())
        no_evidence = []
        for field_name in check_fields:
            if field_name in result.fields:
                field = result.fields[field_name]
                if field.value is not None and not field.evidence:
                    no_evidence.append(field_name)
        if no_evidence:
            return f"No evidence for field(s): {', '.join(no_evidence)}"
        return None
