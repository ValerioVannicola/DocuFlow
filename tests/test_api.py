from __future__ import annotations

import pytest
from pydantic import BaseModel

from docuflow.extraction.llm.base import LLMResponse
from docuflow.processor import DocumentPipeline


class SimpleSchema(BaseModel):
    name: str
    value: float


class FakeLLM:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def complete(self, messages, response_format=None, temperature=0.0):
        self.calls.append(messages)
        return LLMResponse(
            content=(
                '{"data": {"name": "Mario Rossi", "value": 42.5}, '
                '"evidence": {"name": {"page": 0, "text": "Mario Rossi"}, '
                '"value": {"page": 0, "text": "42.5"}}}'
            ),
            model=self.model,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def test_public_all_exports_resolve():
    import docuflow

    for name in docuflow.__all__:
        assert getattr(docuflow, name) is not None


class TestDocumentPipeline:
    def test_init_with_defaults(self):
        pipeline = DocumentPipeline()
        assert pipeline._model == "openai/gpt-4o"
        assert pipeline._parser == "auto"
        assert pipeline._normalize_output is False

    def test_init_with_custom(self):
        pipeline = DocumentPipeline(
            parser="pdfplumber",
            model="anthropic:claude-sonnet-4-20250514",
            storage="local",
            normalize_output=True,
        )
        assert pipeline._model == "anthropic:claude-sonnet-4-20250514"
        assert pipeline._normalize_output is True

    def test_resolve_parser_pdfplumber(self):
        pipeline = DocumentPipeline(parser="pdfplumber")
        parser = pipeline._resolve_parser()
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser

        assert isinstance(parser, PdfplumberParser)

    def test_resolve_parser_unknown_raises(self):
        pipeline = DocumentPipeline(parser="unknown")
        with pytest.raises(ValueError, match="Unknown parser"):
            pipeline._resolve_parser()

    def test_resolve_default_parser_for_text_source(self):
        pipeline = DocumentPipeline()
        assert pipeline._resolve_parser_for_source("text") is None

    def test_resolve_default_parser_for_image_source(self):
        pipeline = DocumentPipeline()
        parser = pipeline._resolve_parser_for_source("image")
        from docuflow.parsing.tesseract_parser import TesseractParser

        assert isinstance(parser, TesseractParser)

    def test_parserless_pdf_text_extraction_rejected(self):
        pipeline = DocumentPipeline(parser=None)
        with pytest.raises(ValueError, match="text-like inputs"):
            pipeline._validate_parserless_source("pdf")

    async def test_parserless_text_file_runs_extraction(self, tmp_path):
        text_path = tmp_path / "claim.txt"
        text_path.write_text("Name: Mario Rossi\nValue: 42.5", encoding="utf-8")
        llm = FakeLLM()
        pipeline = DocumentPipeline(parser=None)
        pipeline._resolve_llm = lambda: llm  # type: ignore[method-assign]

        result = await pipeline.run(str(text_path), SimpleSchema)

        assert result.data == {"name": "Mario Rossi", "value": 42.5}
        assert result.raw_text == "Name: Mario Rossi\nValue: 42.5"
        assert llm.calls

    async def test_default_pipeline_reads_text_file_without_parser(self, tmp_path):
        text_path = tmp_path / "claim.md"
        text_path.write_text("Name: Mario Rossi\nValue: 42.5", encoding="utf-8")
        llm = FakeLLM()
        pipeline = DocumentPipeline()
        pipeline._resolve_llm = lambda: llm  # type: ignore[method-assign]

        result = await pipeline.run(str(text_path), SimpleSchema)

        assert result.data["name"] == "Mario Rossi"
        assert result.raw_text == "Name: Mario Rossi\nValue: 42.5"

    def test_resolve_storage_none(self):
        pipeline = DocumentPipeline(storage=None)
        assert pipeline._resolve_storage() is None

    def test_resolve_storage_local(self):
        pipeline = DocumentPipeline(storage="local")
        storage = pipeline._resolve_storage()
        from docuflow.storage.local import LocalDocumentStore

        assert isinstance(storage, LocalDocumentStore)

    def test_resolve_storage_unknown_raises(self):
        pipeline = DocumentPipeline(storage="unknown")
        with pytest.raises(ValueError, match="Unknown storage"):
            pipeline._resolve_storage()
