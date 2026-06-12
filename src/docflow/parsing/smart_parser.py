from __future__ import annotations

from pathlib import Path

from docflow.constants import DEFAULT_DPI
from docflow.documents.models import BlockType, Document, Page
from docflow.errors import ParsingError

_MIN_TEXT_LENGTH = 20
_MIN_TEXT_COVERAGE = 0.15


def _page_needs_ocr(page: Page) -> bool:
    text = page.text.strip()
    if len(text) < _MIN_TEXT_LENGTH:
        return True

    text_blocks = [b for b in page.blocks if b.block_type == BlockType.TEXT and b.text.strip()]
    if not text_blocks:
        return True

    has_images = any(b.block_type == BlockType.IMAGE for b in page.blocks)
    if has_images and len(text) < 100:
        return True

    garbled_chars = sum(1 for c in text if ord(c) > 0xF000)
    return len(text) > 0 and garbled_chars / len(text) > 0.1


class SmartParser:
    """Tries native PDF text first, falls back to OCR only for pages that need it.

    For each page:
    1. Extract text with pdfplumber (no OCR)
    2. Check if the page has enough usable text
    3. If not (scanned, sparse, garbled, image-heavy), OCR that page with Tesseract
    4. Keep the best result per page
    """

    def __init__(
        self,
        ocr_languages: list[str] | None = None,
        dpi: int = DEFAULT_DPI,
        min_text_length: int = _MIN_TEXT_LENGTH,
    ):
        self.ocr_languages = ocr_languages or ["eng"]
        self.dpi = dpi
        self.min_text_length = min_text_length

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        from docflow.parsing.pdfplumber_parser import PdfplumberParser

        native = PdfplumberParser()
        document = await native.parse(document)

        pages_needing_ocr = [p for p in document.pages if _page_needs_ocr(p)]

        if not pages_needing_ocr:
            return document

        from docflow.ocr.base import blocks_to_points
        from docflow.ocr.tesseract import TesseractOCR
        from docflow.rendering.renderer import render_page

        ocr = TesseractOCR(
            languages=self.ocr_languages,
            preprocess_steps=[],
        )

        # OCR'd pages convert to points so they share the coordinate space
        # of the native-parsed pages in the same document.
        scale = 72.0 / self.dpi
        for page in pages_needing_ocr:
            image = await render_page(file_path, page.page_number, dpi=self.dpi)
            lang = "+".join(self.ocr_languages)
            ocr_result = await ocr.ocr(image, language=lang)

            ocr_page = Page(
                page_number=page.page_number,
                width=float(image.width) * scale,
                height=float(image.height) * scale,
                blocks=blocks_to_points(ocr_result.blocks, self.dpi),
                text=ocr_result.text,
            )

            idx = next(
                i for i, p in enumerate(document.pages)
                if p.page_number == page.page_number
            )
            document.pages[idx] = ocr_page

        document.raw_text = "\n\n".join(p.text for p in document.pages)
        return document
