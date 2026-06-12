from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docflow.documents.models import Block, BoundingBox
from docflow.privacy.models import PrivacyFinding
from docflow.privacy.provider import PrivacyProvider

if TYPE_CHECKING:
    from PIL.Image import Image


def _finding_bbox(block: Block, finding) -> BoundingBox | None:
    """Union bbox of the words overlapping the finding's char range.

    Blocks are line-level; redacting the whole line for one PII token inside
    it blacks out unrelated text. With word detail available, redact only
    the words the finding actually covers.
    """
    if not block.words:
        return None

    matched: list[BoundingBox] = []
    offset = 0
    for word in block.words:
        start, end = offset, offset + len(word.text)
        if start < finding.end and end > finding.start and word.bbox is not None:
            matched.append(word.bbox)
        offset = end + 1  # words join with a single space in block.text

    if not matched:
        return None
    return BoundingBox(
        x0=min(b.x0 for b in matched),
        y0=min(b.y0 for b in matched),
        x1=max(b.x1 for b in matched),
        y1=max(b.y1 for b in matched),
    )


class ImageRedactor:
    def __init__(self, provider: PrivacyProvider, ocr_engine: Any = None):
        self.provider = provider
        self._ocr_engine = ocr_engine

    def _get_ocr_engine(self) -> Any:
        if self._ocr_engine is not None:
            return self._ocr_engine
        from docflow.ocr.tesseract import TesseractOCR

        return TesseractOCR(preprocess_steps=[])

    async def redact_page_image(
        self,
        image: Image,
        language: str = "eng",
        entities: list[str] | None = None,
    ) -> tuple[Image, list[PrivacyFinding]]:
        from PIL import ImageDraw

        ocr = self._get_ocr_engine()
        ocr_result = await ocr.ocr(image, language=language)

        all_findings: list[PrivacyFinding] = []
        redact_regions: list[tuple[float, float, float, float]] = []

        for block in ocr_result.blocks:
            if not block.text.strip() or block.bbox is None:
                continue

            findings = await self.provider.adetect_text(
                block.text,
                entities=entities,
            )

            for finding in findings:
                region_bbox = _finding_bbox(block, finding) or block.bbox
                all_findings.append(
                    PrivacyFinding(
                        entity_type=finding.entity_type,
                        start=finding.start,
                        end=finding.end,
                        text=finding.text,
                        score=finding.score,
                        bbox=region_bbox,
                    )
                )
                redact_regions.append(
                    (region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1)
                )

        if redact_regions:
            redacted = image.copy()
            draw = ImageDraw.Draw(redacted)
            for region in redact_regions:
                draw.rectangle(region, fill="black")
            return redacted, all_findings

        return image, all_findings
