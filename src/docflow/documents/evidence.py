from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from docflow.documents.models import BoundingBox


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    page_number: int
    text: str
    bbox: BoundingBox | None = None
    block_id: str | None = None
    confidence: float | None = None
