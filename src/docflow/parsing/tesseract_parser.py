from __future__ import annotations

from pathlib import Path

from docflow.constants import DEFAULT_DPI
from docflow.documents.models import Document, Page
from docflow.errors import ParsingError


class TesseractParser:
    def __init__(
        self,
        languages: list[str] | None = None,
        dpi: int = DEFAULT_DPI,
        preprocess_steps: list[str] | None = None,
    ):
        self.languages = languages or ["eng"]
        self.dpi = dpi
        self.preprocess_steps = preprocess_steps

    async def parse(self, document: Document) -> Document:
        file_path = document.metadata.file_path
        if not Path(file_path).is_file():
            raise ParsingError(f"File not found: {file_path}")

        from docflow.ocr.tesseract import TesseractOCR
        from docflow.rendering.renderer import render_all_pages

        images = await render_all_pages(file_path, dpi=self.dpi)

        ocr = TesseractOCR(
            languages=self.languages,
            preprocess_steps=self.preprocess_steps,
        )

        pages: list[Page] = []
        for i, image in enumerate(images):
            lang = "+".join(self.languages)
            ocr_result = await ocr.ocr(image, language=lang)
            pages.append(
                Page(
                    page_number=i,
                    width=float(image.width),
                    height=float(image.height),
                    blocks=ocr_result.blocks,
                    text=ocr_result.text,
                )
            )

        document.pages = pages
        document.raw_text = "\n\n".join(p.text for p in pages)
        document.metadata.page_count = len(pages)
        document.status = "parsed"
        return document
