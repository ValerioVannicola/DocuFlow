from __future__ import annotations

import pytest
from pydantic import BaseModel

from docflow.processor import DocumentPipeline


class SimpleSchema(BaseModel):
    name: str
    value: float


class TestDocumentPipeline:
    def test_init_with_defaults(self):
        pipeline = DocumentPipeline()
        assert pipeline._model == "openai/gpt-4o"
        assert pipeline._parser == "pdfplumber"

    def test_init_with_custom(self):
        pipeline = DocumentPipeline(
            parser="pdfplumber",
            model="anthropic:claude-sonnet-4-20250514",
            storage="local",
        )
        assert pipeline._model == "anthropic:claude-sonnet-4-20250514"

    def test_resolve_parser_pdfplumber(self):
        pipeline = DocumentPipeline(parser="pdfplumber")
        parser = pipeline._resolve_parser()
        from docflow.parsing.pdfplumber_parser import PdfplumberParser

        assert isinstance(parser, PdfplumberParser)

    def test_resolve_parser_unknown_raises(self):
        pipeline = DocumentPipeline(parser="unknown")
        with pytest.raises(ValueError, match="Unknown parser"):
            pipeline._resolve_parser()

    def test_resolve_storage_none(self):
        pipeline = DocumentPipeline(storage=None)
        assert pipeline._resolve_storage() is None

    def test_resolve_storage_local(self):
        pipeline = DocumentPipeline(storage="local")
        storage = pipeline._resolve_storage()
        from docflow.storage.local import LocalDocumentStore

        assert isinstance(storage, LocalDocumentStore)

    def test_resolve_storage_unknown_raises(self):
        pipeline = DocumentPipeline(storage="unknown")
        with pytest.raises(ValueError, match="Unknown storage"):
            pipeline._resolve_storage()
