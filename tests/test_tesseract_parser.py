from __future__ import annotations

import pytest

from docuflow.documents.models import Document, DocumentMetadata
from docuflow.parsing.base import Parser
from docuflow.parsing.tesseract_parser import TesseractParser


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
        from tests.conftest import make_test_pdf

        pdf_path = tmp_path / "test.pdf"
        make_test_pdf(pdf_path, [(72, 72, "Hello World Test Document")])

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
        from docuflow.workflow.steps import Parse

        step = Parse(parser="tesseract")
        assert step.parser == "tesseract"

    def test_processor_resolves_tesseract(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="tesseract")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, TesseractParser)

    def test_processor_resolves_pdfplumber(self):
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="pdfplumber")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, PdfplumberParser)

    def test_processor_unknown_raises(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="unknown")
        with pytest.raises(ValueError, match="Unknown parser"):
            pipeline._resolve_parser()
