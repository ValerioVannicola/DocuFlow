from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from docflow.documents.evidence import Evidence

T = TypeVar("T")


class FieldTrust(BaseModel):
    agreement: str = ""
    agreement_ratio: float = 0.0
    found_in_source: bool = False
    valid: bool = True
    auto_accept: bool = False
    score: float = 0.0
    explanation: str = ""


class ExtractedField(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: Any = None
    original_value: Any = None
    corrected: bool = False
    confidence: float = 0.0
    trust: FieldTrust | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    validation_status: str = "pending"
    errors: list[str] = Field(default_factory=list)


class FieldCorrection(BaseModel):
    field_name: str
    old_value: Any = None
    new_value: Any = None
    corrected_by: str = ""
    reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class ReviewVerdict(BaseModel):
    reviewer: str
    verdict: str
    reasoning: str = ""


class FieldProvenance(BaseModel):
    field_name: str
    value: Any = None
    original_value: Any = None
    corrected: bool = False
    confidence: float = 0.0
    source_text: str = ""
    page: int | None = None
    bbox: Any = None
    block_id: str | None = None
    evidence_confidence: float | None = None
    model_name: str = ""
    parser_name: str = ""
    validation_status: str = "pending"
    validation_errors: list[str] = Field(default_factory=list)
    reviewed: bool = False
    review_status: str = "pending"
    reviewed_by: str = ""
    review_verdicts: list[str] = Field(default_factory=list)
    corrected_by: str = ""
    correction_reason: str = ""


class ExtractionResult(BaseModel):
    document_id: str
    schema_name: str
    data: dict = Field(default_factory=dict)
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    confidence: float = 0.0
    needs_review: bool = False
    review_status: str = "pending"
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    rejection_reason: str = ""
    review_reasons: list[str] = Field(default_factory=list)
    review_verdicts: list[ReviewVerdict] = Field(default_factory=list)
    corrections: list[FieldCorrection] = Field(default_factory=list)
    validation_errors: list[dict] = Field(default_factory=list)
    trace_id: str = ""
    model_name: str = ""
    parser_name: str = ""

    def correct_field(
        self,
        field_name: str,
        new_value: Any,
        corrected_by: str = "",
        reason: str = "",
    ) -> None:
        if field_name not in self.fields:
            raise KeyError(f"Field '{field_name}' not found in extraction result")

        field = self.fields[field_name]
        old_value = field.value

        if not field.corrected:
            field.original_value = old_value

        field.value = new_value
        field.corrected = True
        self.data[field_name] = new_value

        self.corrections.append(
            FieldCorrection(
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                corrected_by=corrected_by,
                reason=reason,
            )
        )

    def approve(self, approved_by: str = "") -> None:
        if self.review_status in ("approved", "rejected"):
            raise ValueError(
                f"Cannot approve: review_status is already '{self.review_status}'"
            )
        self.review_status = "approved"
        self.reviewed_by = approved_by
        self.reviewed_at = datetime.now()

    def reject(self, rejected_by: str = "", reason: str = "") -> None:
        if self.review_status in ("approved", "rejected"):
            raise ValueError(
                f"Cannot reject: review_status is already '{self.review_status}'"
            )
        self.review_status = "rejected"
        self.reviewed_by = rejected_by
        self.reviewed_at = datetime.now()
        self.rejection_reason = reason

    def provenance(self, field_name: str | None = None) -> dict[str, FieldProvenance]:
        result: dict[str, FieldProvenance] = {}
        check_fields = [field_name] if field_name else list(self.fields.keys())

        field_corrections: dict[str, FieldCorrection] = {}
        for c in self.corrections:
            field_corrections[c.field_name] = c

        field_verdicts: dict[str, list[str]] = {}
        for v in self.review_verdicts:
            for fname in check_fields:
                if fname not in field_verdicts:
                    field_verdicts[fname] = []
                field_verdicts[fname].append(f"{v.reviewer}: {v.verdict}")

        for fname in check_fields:
            if fname not in self.fields:
                continue
            field = self.fields[fname]

            source_text = ""
            page = None
            bbox = None
            block_id = None
            ev_confidence = None
            if field.evidence:
                ev = field.evidence[0]
                source_text = ev.text
                page = ev.page_number
                bbox = ev.bbox
                block_id = ev.block_id
                ev_confidence = ev.confidence

            correction = field_corrections.get(fname)

            result[fname] = FieldProvenance(
                field_name=fname,
                value=field.value,
                original_value=field.original_value,
                corrected=field.corrected,
                confidence=field.confidence,
                source_text=source_text,
                page=page,
                bbox=bbox,
                block_id=block_id,
                evidence_confidence=ev_confidence,
                model_name=self.model_name,
                parser_name=self.parser_name,
                validation_status=field.validation_status,
                validation_errors=field.errors,
                reviewed=self.review_status != "pending",
                review_status=self.review_status,
                reviewed_by=self.reviewed_by,
                review_verdicts=field_verdicts.get(fname, []),
                corrected_by=correction.corrected_by if correction else "",
                correction_reason=correction.reason if correction else "",
            )

        return result
