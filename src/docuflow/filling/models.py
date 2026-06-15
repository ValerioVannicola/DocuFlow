from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docuflow.documents.models import BoundingBox
from docuflow.observability.traces import Trace

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
    data: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, FilledField] = Field(default_factory=dict)
    pdf_fields: list[FormField] = Field(default_factory=list)
    unmapped_model_fields: list[str] = Field(default_factory=list)
    unmapped_pdf_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: str = ""
    trace: Trace | None = Field(default=None, exclude=True)
