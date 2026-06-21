from __future__ import annotations

import pytest

from docuflow.documents.models import Document, DocumentMetadata
from docuflow.parsing.base import Parser
from docuflow.parsing.markitdown_parser import MarkitdownParser


class TestMarkitdownParser:
    def test_protocol_compliance(self):
        assert isinstance(MarkitdownParser(), Parser)

    @pytest.mark.integration
    async def test_parse_real_pdf(self, tmp_path):
        pytest.importorskip("markitdown", reason="markitdown extra is not installed")
        from tests.conftest import make_test_pdf

        pdf_path = tmp_path / "test.pdf"
        make_test_pdf(pdf_path, [
            (72, 72, "Hello World - Markitdown Test"),
            (72, 120, "Invoice Number: INV-001"),
            (72, 150, "Total: 1234.56"),
        ])

        document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf",
                file_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                mime_type="application/pdf",
            ),
        )

        parser = MarkitdownParser()
        result = await parser.parse(document)

        assert result.status == "parsed"
        assert result.metadata.page_count == 1
        assert "INV-001" in result.raw_text
        assert len(result.pages) == 1
        assert len(result.pages[0].blocks) == 1

        block = result.pages[0].blocks[0]
        assert block.confidence is None
        assert block.bbox is None
        assert block.words == []

    async def test_parse_nonexistent_file(self):
        from docuflow.errors import ParsingError

        document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="missing.pdf",
                file_path="nonexistent.pdf",
                mime_type="application/pdf",
            ),
        )

        parser = MarkitdownParser()
        with pytest.raises(ParsingError):
            await parser.parse(document)


class TestParseStepMarkitdown:
    def test_processor_resolves_markitdown(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="markitdown")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, MarkitdownParser)

    async def test_parse_step_resolves_markitdown_string(self):
        from docuflow.workflow.steps import Parse

        step = Parse(parser="markitdown")
        assert step.parser == "markitdown"

    def test_workflow_config_exports_markitdown(self):
        from docuflow.workflow_config import _export_parser

        assert _export_parser(_FakePipeline(MarkitdownParser())) == "markitdown"


class _FakePipeline:
    def __init__(self, parser):
        self._parser = parser
