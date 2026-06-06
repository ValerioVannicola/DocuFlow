from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from docflow.documents.models import Block

if TYPE_CHECKING:
    from PIL.Image import Image


class OCRResult(BaseModel):
    text: str = ""
    confidence: float = 0.0
    blocks: list[Block] = Field(default_factory=list)
    language: str = "eng"
    mean_word_confidence: float = 0.0
    low_confidence_word_ratio: float = 0.0
    word_count: int = 0


@runtime_checkable
class OCREngine(Protocol):
    async def ocr(self, image: Image, language: str = "eng") -> OCRResult: ...
