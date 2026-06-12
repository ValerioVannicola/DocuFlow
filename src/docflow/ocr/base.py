from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from docflow.documents.models import Block, BoundingBox

if TYPE_CHECKING:
    from PIL.Image import Image


def _scale_bbox(bbox: BoundingBox | None, factor: float) -> BoundingBox | None:
    if bbox is None:
        return None
    return BoundingBox(
        x0=bbox.x0 * factor, y0=bbox.y0 * factor,
        x1=bbox.x1 * factor, y1=bbox.y1 * factor,
    )


def blocks_to_points(blocks: list[Block], dpi: int) -> list[Block]:
    """Convert OCR blocks from rendered-image pixels to PDF points.

    OCR runs on pages rendered at `dpi`; the canonical document coordinate
    space is points (72/inch), so all bboxes scale by 72/dpi.
    """
    factor = 72.0 / dpi
    scaled: list[Block] = []
    for block in blocks:
        scaled.append(
            block.model_copy(
                update={
                    "bbox": _scale_bbox(block.bbox, factor),
                    "words": [
                        w.model_copy(update={"bbox": _scale_bbox(w.bbox, factor)})
                        for w in block.words
                    ],
                }
            )
        )
    return scaled


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
