from __future__ import annotations

import pytest

from docflow.documents.models import Document, DocumentMetadata
from docflow.parsing.base import Parser
from docflow.parsing.docling_parser import DoclingParser


class TestDoclingParser:
    def test_protocol_compliance(self):
        assert isinstance(DoclingParser(), Parser)

    @pytest.mark.integration
    async def test_parse_real_pdf(self, tmp_path):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed for test PDF creation")

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello World - Docling Test")
        page.insert_text((72, 120), "Invoice Number: INV-001")
        page.insert_text((72, 150), "Total: 1234.56")
        doc.save(str(pdf_path))
        doc.close()

        document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf",
                file_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                mime_type="application/pdf",
            ),
        )

        parser = DoclingParser()
        result = await parser.parse(document)

        assert result.status == "parsed"
        assert result.metadata.page_count >= 1
        assert result.raw_text != ""
        assert len(result.pages) >= 1
        assert len(result.pages[0].blocks) > 0

    async def test_parse_nonexistent_file(self):
        from docflow.errors import ParsingError

        document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="missing.pdf",
                file_path="nonexistent.pdf",
                mime_type="application/pdf",
            ),
        )

        parser = DoclingParser()
        with pytest.raises(ParsingError):
            await parser.parse(document)


class TestDoclingOCRConfidence:
    def _bbox(self, left, top, right, bottom):
        from types import SimpleNamespace

        return SimpleNamespace(
            l=left, t=top, r=right, b=bottom, coord_origin="TOPLEFT",
        )

    def _ocr_cell(self, text, conf, left, top, right, bottom):
        from types import SimpleNamespace

        return SimpleNamespace(
            text=text,
            confidence=conf,
            from_ocr=True,
            bbox=self._bbox(left, top, right, bottom),
        )

    def _native_cell(self, text, left, top, right, bottom):
        from types import SimpleNamespace

        return SimpleNamespace(
            text=text,
            from_ocr=False,
            bbox=self._bbox(left, top, right, bottom),
        )

    def test_ocr_cells_become_words(self):
        from docflow.parsing.docling_parser import _cell_to_word

        word = _cell_to_word(self._ocr_cell("Total", 0.91, 10, 10, 60, 25), 842.0)
        assert word is not None
        assert word.text == "Total"
        assert word.confidence == 0.91
        assert word.bbox.x0 == 10

    def test_native_cells_skipped(self):
        from docflow.parsing.docling_parser import _cell_to_word

        assert _cell_to_word(self._native_cell("Total", 10, 10, 60, 25), 842.0) is None

    def test_old_api_ocr_cell_detected_by_class_name(self):
        from docflow.parsing.docling_parser import _cell_to_word

        ocr_cell_cls = type("OcrCell", (), {})
        cell = ocr_cell_cls()
        cell.text = "Acme"
        cell.confidence = 0.88
        cell.bbox = self._bbox(10, 10, 50, 25)
        cell.from_ocr = None
        word = _cell_to_word(cell, 842.0)
        assert word is not None
        assert word.confidence == 0.88

    def test_words_attached_to_blocks_by_bbox(self):
        from docflow.documents.models import Block, BlockType, BoundingBox
        from docflow.parsing.docling_parser import (
            _attach_words_to_blocks,
            _cell_to_word,
        )

        block = Block(
            block_id="b1",
            block_type=BlockType.TEXT,
            text="Total: 100.00",
            bbox=BoundingBox(x0=0, y0=0, x1=200, y1=30),
        )
        far_block = Block(
            block_id="b2",
            block_type=BlockType.TEXT,
            text="Footer",
            bbox=BoundingBox(x0=0, y0=700, x1=200, y1=730),
        )
        words = [
            _cell_to_word(self._ocr_cell("Total:", 0.95, 5, 5, 60, 25), 842.0),
            _cell_to_word(self._ocr_cell("100.00", 0.85, 70, 5, 130, 25), 842.0),
        ]

        blocks = _attach_words_to_blocks([block, far_block], words)

        assert [w.text for w in blocks[0].words] == ["Total:", "100.00"]
        assert blocks[0].confidence == pytest.approx(0.90)
        assert blocks[1].words == []
        assert blocks[1].confidence is None

    def test_harvest_requires_matching_page_count(self):
        from types import SimpleNamespace

        from docflow.parsing.docling_parser import _harvest_ocr_words

        result = SimpleNamespace(
            pages=[SimpleNamespace(cells=[self._ocr_cell("x", 0.9, 0, 0, 10, 10)])]
        )
        # 2 document pages but 1 conversion page: bail out rather than misalign
        assert _harvest_ocr_words(result, [1, 2], {1: (595, 842), 2: (595, 842)}) == {}

    def test_harvest_collects_words_per_page(self):
        from types import SimpleNamespace

        from docflow.parsing.docling_parser import _harvest_ocr_words

        result = SimpleNamespace(
            pages=[
                SimpleNamespace(
                    cells=[
                        self._ocr_cell("Invoice", 0.97, 0, 0, 50, 10),
                        self._native_cell("ignored", 0, 20, 50, 30),
                    ]
                )
            ]
        )
        words = _harvest_ocr_words(result, [1], {1: (595.0, 842.0)})
        assert list(words.keys()) == [1]
        assert [w.text for w in words[1]] == ["Invoice"]


class TestParseStepDocling:
    def test_processor_resolves_docling(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="docling")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, DoclingParser)

    async def test_parse_step_resolves_docling_string(self):
        from docflow.workflow.steps import Parse

        step = Parse(parser="docling")
        assert step.parser == "docling"
