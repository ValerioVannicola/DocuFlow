from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from docflow.documents.evidence import Evidence
from docflow.documents.models import BoundingBox, PageRect

T = TypeVar("T")


class TokenUsage(BaseModel):
    """Aggregated LLM token usage for an extraction.

    Sums every LLM call made to produce the result: extraction instances,
    decider, JSON-repair retries and LLM reviewers. `cost_usd` is filled
    when the adapter can price the model (litellm), else None.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_llm_calls: int = 0
    cost_usd: float | None = None

    def merged(self, usage: dict) -> TokenUsage:
        """Return a new TokenUsage with one call's usage dict added."""
        cost = usage.get("cost_usd")
        new_cost = self.cost_usd
        if cost is not None:
            new_cost = round((new_cost or 0.0) + cost, 6)
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=self.completion_tokens
            + int(usage.get("completion_tokens", 0) or 0),
            total_tokens=self.total_tokens + int(usage.get("total_tokens", 0) or 0),
            n_llm_calls=self.n_llm_calls + 1,
            cost_usd=new_cost,
        )

    def combined(self, other: TokenUsage) -> TokenUsage:
        """Return a new TokenUsage adding another aggregate (e.g. per-document
        usages into a batch total)."""
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = round((self.cost_usd or 0.0) + (other.cost_usd or 0.0), 6)
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            n_llm_calls=self.n_llm_calls + other.n_llm_calls,
            cost_usd=cost,
        )

    @classmethod
    def from_usages(cls, usages: list[dict]) -> TokenUsage | None:
        if not usages:
            return None
        total = cls()
        for u in usages:
            total = total.merged(u)
        return total


class OCRFieldConfidence(BaseModel):
    """OCR confidence for one field, matched back from the extracted value.

    `score` is the minimum word confidence in the matched span (a field read
    is only as trustworthy as its worst word). None when the value could not
    be matched back to any OCR text. `bbox` is the union highlight rect for
    single-page matches; `rects` carries one rect per (page, line) segment
    for spans crossing lines or pages.
    """

    score: float | None = None
    match_method: str = "unmatched"  # "exact_block" | "fuzzy_block" | "page_text" | "unmatched"
    match_ratio: float = 0.0
    matched_text: str = ""
    page_number: int | None = None
    bbox: BoundingBox | None = None
    rects: list[PageRect] = Field(default_factory=list)


class OCRDocumentConfidence(BaseModel):
    score: float = 0.0
    word_count: int = 0
    low_confidence_ratio: float = 0.0


class FieldConsensus(BaseModel):
    """Cross-instance agreement for one field (multi-instance extraction only).

    `agreement_ratio` measures agreement with the final (decider-chosen)
    value; `majority_ratio` measures the largest candidate cluster. When
    agreement_ratio < majority_ratio the decider overrode the majority.
    """

    n_instances: int = 0
    n_succeeded: int = 0
    agreement: str = "0/0"
    agreement_ratio: float = 0.0
    majority_ratio: float = 0.0


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
    ocr: OCRFieldConfidence | None = None
    consensus: FieldConsensus | None = None
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
    usage: dict = Field(default_factory=dict)


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
    ocr: OCRDocumentConfidence | None = None
    usage: TokenUsage | None = None
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
