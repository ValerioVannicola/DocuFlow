from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docuflow.documents.models import BoundingBox
from docuflow.observability.traces import Trace

# Sentinel for "argument not provided" so callers can edit a value to None/False.
_UNSET: Any = object()

FillStrategy = Literal["auto", "acroform", "overlay"]
MatchStrategy = Literal["auto", "name", "alias", "manual", "label", "llm"]
BlankDetectionMode = Literal["heuristic", "llm", "hybrid"]
UnmatchedPolicy = Literal["error", "warn", "ignore"]
OverflowPolicy = Literal["error", "shrink", "wrap"]


class FieldPlacement(BaseModel):
    """Explicit placement for static PDF overlay filling.

    Coordinates use DocuFlow's document geometry convention: page-local,
    top-left origin, usually PDF points.
    """

    page_number: int = 0
    bbox: BoundingBox
    font_size: float = 10.0
    font_name: str = "Helvetica"
    align: Literal["left", "center", "right"] = "left"
    multiline: bool = False
    source: str = ""
    label_text: str = ""
    confidence: float | None = None
    reason: str = ""
    control_type: str = "text"


class FormField(BaseModel):
    """A writable field discovered in a PDF form."""

    name: str
    field_type: str = "unknown"
    page_number: int | None = None
    bbox: BoundingBox | None = None
    options: list[str] = Field(default_factory=list)
    current_value: Any = None
    required: bool = False


class FilledField(BaseModel):
    """One model field written into one PDF target."""

    field_name: str
    value: Any = None
    formatted_value: Any = None
    target_name: str = ""
    page_number: int | None = None
    bbox: BoundingBox | None = None
    placement: FieldPlacement | None = None
    method: str = ""
    status: Literal["filled", "skipped", "failed"] = "filled"
    warnings: list[str] = Field(default_factory=list)
    # Review state (mirrors ExtractedField)
    original_value: Any = None
    corrected: bool = False


class FillCorrection(BaseModel):
    """One reviewer edit to a planned fill, before the PDF is written."""

    field_name: str
    old_value: Any = None
    new_value: Any = None
    old_placement: FieldPlacement | None = None
    new_placement: FieldPlacement | None = None
    corrected_by: str = ""
    reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class FillPlan(BaseModel):
    """Internal write plan produced before modifying the PDF."""

    strategy: Literal["acroform", "overlay"]
    assignments: dict[str, Any] = Field(default_factory=dict)
    placements: dict[str, FieldPlacement] = Field(default_factory=dict)
    fields: dict[str, FilledField] = Field(default_factory=dict)
    pdf_fields: list[FormField] = Field(default_factory=list)
    unmapped_model_fields: list[str] = Field(default_factory=list)
    unmapped_pdf_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FillingResult(BaseModel):
    """Result returned by PDF form filling.

    This is intentionally separate from ExtractionResult: filling writes
    trusted user data into a document, while extraction reads a document into
    structured data.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    input_path: str
    document_id: str = ""
    output_path: str = ""
    schema_name: str = ""
    strategy: Literal["acroform", "overlay", ""] = ""
    success: bool = False
    committed: bool = False
    data: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, FilledField] = Field(default_factory=dict)
    pdf_fields: list[FormField] = Field(default_factory=list)
    unmapped_model_fields: list[str] = Field(default_factory=list)
    unmapped_pdf_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Write options preserved so a deferred commit reproduces the original intent.
    flatten: bool = False
    overflow: OverflowPolicy = "shrink"
    # Review state (mirrors ExtractionResult)
    needs_review: bool = False
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    rejection_reason: str = ""
    review_reasons: list[str] = Field(default_factory=list)
    corrections: list[FillCorrection] = Field(default_factory=list)
    trace_id: str = ""
    trace: Trace | None = Field(default=None, exclude=True)

    def edit_field(
        self,
        field_name: str,
        *,
        value: Any = _UNSET,
        bbox: BoundingBox | dict[str, Any] | None = None,
        page_number: int | None = None,
        font_size: float | None = None,
        align: Literal["left", "center", "right"] | None = None,
        corrected_by: str = "",
        reason: str = "",
    ) -> None:
        """Edit a planned fill before commit: change the value, the placement, or both.

        Pass ``value=`` to change what is written; pass any of ``bbox`` /
        ``page_number`` / ``font_size`` / ``align`` to change where/how it is
        written (overlay strategy). The original value/placement is preserved on
        first edit and a :class:`FillCorrection` is appended to the audit log.
        """
        from docuflow.filling.planner import format_value

        if field_name not in self.fields:
            raise KeyError(f"Field '{field_name}' not found in filling result")
        if self.committed:
            raise ValueError("Cannot edit fields after the PDF has been committed.")
        if self.review_status == "rejected":
            raise ValueError("Cannot edit a rejected filling result.")

        field = self.fields[field_name]
        value_changed = value is not _UNSET
        placement_changed = any(
            arg is not None for arg in (bbox, page_number, font_size, align)
        )
        if not value_changed and not placement_changed:
            raise ValueError("edit_field requires a value and/or a placement change.")

        old_value = field.value
        old_placement = field.placement.model_copy(deep=True) if field.placement else None
        if not field.corrected:
            field.original_value = old_value

        if value_changed:
            field.value = value
            form_field = next(
                (f for f in self.pdf_fields if f.name == field.target_name), None
            )
            field.formatted_value = format_value(value, form_field=form_field)
            self.data[field_name] = value

        new_placement = old_placement
        if placement_changed:
            base = field.placement or FieldPlacement(
                page_number=field.page_number or 0,
                bbox=field.bbox or BoundingBox(x0=0, y0=0, x1=0, y1=0),
            )
            updates: dict[str, Any] = {}
            if bbox is not None:
                updates["bbox"] = (
                    bbox if isinstance(bbox, BoundingBox) else BoundingBox.model_validate(bbox)
                )
            if page_number is not None:
                updates["page_number"] = page_number
            if font_size is not None:
                updates["font_size"] = font_size
            if align is not None:
                updates["align"] = align
            new_placement = base.model_copy(update=updates)
            field.placement = new_placement
            field.bbox = new_placement.bbox
            field.page_number = new_placement.page_number

        field.corrected = True
        self.corrections.append(
            FillCorrection(
                field_name=field_name,
                old_value=old_value,
                new_value=field.value,
                old_placement=old_placement,
                new_placement=new_placement if placement_changed else None,
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
