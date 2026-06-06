from __future__ import annotations

import pytest

from docflow.documents.models import Document, DocumentMetadata
from docflow.parsing.base import Parser
from docflow.parsing.tesseract_parser import TesseractParser


class TestTesseractParser:
    def test_protocol_compliance(self):
        assert isinstance(TesseractParser(), Parser)

    def test_default_config(self):
        p = TesseractParser()
        assert p.languages == ["eng"]
        assert p.dpi == 200

    def test_custom_config(self):
        p = TesseractParser(languages=["eng", "ita"], dpi=300)
        assert p.languages == ["eng", "ita"]
        assert p.dpi == 300


class TestTesseractParserExecution:
    @pytest.mark.integration
    async def test_parse_real_pdf(self, tmp_path):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello World Test Document")
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

        parser = TesseractParser(dpi=150)
        result = await parser.parse(document)

        assert result.status == "parsed"
        assert len(result.pages) == 1
        assert result.metadata.page_count == 1
        assert result.raw_text != ""
        assert result.pages[0].width > 0
        assert result.pages[0].height > 0
        assert len(result.pages[0].blocks) > 0
        assert result.pages[0].blocks[0].bbox is not None
        assert result.pages[0].blocks[0].confidence is not None


class TestParseStepResolution:
    async def test_parse_step_resolves_tesseract_string(self):
        from docflow.workflow.steps import Parse

        step = Parse(parser="tesseract")
        assert step.parser == "tesseract"

    def test_processor_resolves_tesseract(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="tesseract")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, TesseractParser)

    def test_processor_resolves_pymupdf(self):
        from docflow.parsing.pymupdf import PyMuPDFParser
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="pymupdf")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, PyMuPDFParser)

    def test_processor_unknown_raises(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="unknown")
        with pytest.raises(ValueError, match="Unknown parser"):
            pipeline._resolve_parser()
