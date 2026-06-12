from __future__ import annotations

from typing import Protocol, runtime_checkable

from docuflow.documents.models import Document


@runtime_checkable
class Parser(Protocol):
    async def parse(self, document: Document) -> Document: ...
