from __future__ import annotations

from pathlib import Path

import pytest

from docuflow.documents.models import Document, DocumentMetadata
from docuflow.errors import ParsingError
from docuflow.parsing.base import Parser


class TestParserProtocol:
    def test_protocol_is_runtime_checkable(self):
        class FakeParser:
            async def parse(self, document: Document) -> Document:
                return document

        assert isinstance(FakeParser(), Parser)


class TestPdfplumberParser:
    @pytest.mark.integration
    async def test_parse_real_pdf(self, tmp_path):
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        doc = Document(
            id="test-doc",
            metadata=DocumentMetadata(
                file_name="test.pdf",
                file_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                mime_type="application/pdf",
            ),
        )

        parser = PdfplumberParser()
        result = await parser.parse(doc)

        assert result.status == "parsed"
        assert len(result.pages) == 1
        assert result.metadata.page_count == 1
        assert result.raw_text != ""
        assert result.pages[0].width > 0
        assert result.pages[0].height > 0

    @pytest.mark.integration
    async def test_parse_nonexistent_file(self):
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser

        doc = Document(
            id="test-doc",
            metadata=DocumentMetadata(
                file_name="missing.pdf",
                file_path="nonexistent.pdf",
                mime_type="application/pdf",
            ),
        )

        parser = PdfplumberParser()
        with pytest.raises(ParsingError):
            await parser.parse(doc)


def _create_test_pdf(path: Path) -> None:
    from tests.conftest import make_test_pdf

    make_test_pdf(path, [(72, 72, "Hello World - Test Invoice"), (72, 90, "Total: 1234.56")])
