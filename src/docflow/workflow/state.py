from __future__ import annotations

from pydantic import BaseModel, Field

from docflow.documents.models import Document
from docflow.extraction.models import ExtractionResult
from docflow.observability.traces import Trace


class PipelineState(BaseModel):
    document: Document | None = None
    extraction_result: ExtractionResult | None = None
    trace: Trace = Field(default_factory=Trace)
    current_step: str = ""
    status: str = "pending"
    errors: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
