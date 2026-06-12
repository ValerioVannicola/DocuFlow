from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docflow.documents.models import BoundingBox, PageRect


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    page_number: int
    text: str
    bbox: BoundingBox | None = None
    rects: list[PageRect] = Field(default_factory=list)
    block_id: str | None = None
    confidence: float | None = None
