from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from docuflow.documents.models import Document
from docuflow.extraction.models import ExtractionResult


@runtime_checkable
class Strategy(Protocol):
    async def execute(
        self, document: Document, schema: type[BaseModel], **kwargs: object
    ) -> ExtractionResult: ...
