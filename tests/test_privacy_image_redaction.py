from __future__ import annotations

from unittest.mock import AsyncMock

from docflow.documents.models import BoundingBox
from docflow.ocr.base import OCRResult
from docflow.privacy.image_redaction import ImageRedactor
from docflow.privacy.models import PrivacyFinding


def _make_mock_provider(findings: list[PrivacyFinding] | None = None):
    provider = AsyncMock()
    provider.adetect_text = AsyncMock(return_value=findings or [])
    return provider


def _make_mock_ocr(blocks=None):
    from docflow.documents.models import Block, BlockType

    if blocks is None:
        blocks = [
            Block(
                block_id="b1",
                block_type=BlockType.TEXT,
                text="John Doe",
                bbox=BoundingBox(x0=10, y0=20, x1=100, y1=40),
            ),
            Block(
                block_id="b2",
                block_type=BlockType.TEXT,
                text="No PII here",
                bbox=BoundingBox(x0=10, y0=50, x1=200, y1=70),
            ),
        ]

    ocr = AsyncMock()
    ocr.ocr = AsyncMock(return_value=OCRResult(text="John Doe No PII here", blocks=blocks))
    return ocr


class TestImageRedactor:
    async def test_redact_with_pii(self):
        from PIL import Image

        findings = [
            PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95)
        ]
        provider = _make_mock_provider(findings)
        ocr = _make_mock_ocr()

        redactor = ImageRedactor(provider=provider, ocr_engine=ocr)
        img = Image.new("RGB", (300, 100), color="white")
        redacted, found = await redactor.redact_page_image(img)

        assert len(found) >= 1
        assert found[0].entity_type == "PERSON"
        assert found[0].bbox is not None
        pixel = redacted.getpixel((50, 30))
        assert pixel == (0, 0, 0)

    async def test_no_pii_found(self):
        from PIL import Image

        provider = _make_mock_provider([])
        ocr = _make_mock_ocr()

        redactor = ImageRedactor(provider=provider, ocr_engine=ocr)
        img = Image.new("RGB", (300, 100), color="white")
        result_img, found = await redactor.redact_page_image(img)

        assert len(found) == 0
        assert result_img is img

    async def test_empty_blocks(self):
        from PIL import Image

        provider = _make_mock_provider([])
        ocr = AsyncMock()
        ocr.ocr = AsyncMock(return_value=OCRResult(text="", blocks=[]))

        redactor = ImageRedactor(provider=provider, ocr_engine=ocr)
        img = Image.new("RGB", (300, 100), color="white")
        _result_img, found = await redactor.redact_page_image(img)

        assert len(found) == 0
