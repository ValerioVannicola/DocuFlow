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
