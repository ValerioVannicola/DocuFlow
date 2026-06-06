from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docflow.privacy.models import PrivacyFinding
from docflow.privacy.provider import PrivacyProvider

if TYPE_CHECKING:
    from PIL.Image import Image


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
                all_findings.append(
                    PrivacyFinding(
                        entity_type=finding.entity_type,
                        start=finding.start,
                        end=finding.end,
                        text=finding.text,
                        score=finding.score,
                        bbox=block.bbox,
                    )
                )
                redact_regions.append(
                    (block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1)
                )

        if redact_regions:
            redacted = image.copy()
            draw = ImageDraw.Draw(redacted)
            for region in redact_regions:
                draw.rectangle(region, fill="black")
            return redacted, all_findings

        return image, all_findings
