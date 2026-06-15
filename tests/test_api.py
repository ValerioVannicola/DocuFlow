from __future__ import annotations

import pytest
from pydantic import BaseModel

from docuflow.processor import DocumentPipeline


class SimpleSchema(BaseModel):
    name: str
    value: float


def test_public_all_exports_resolve():
    import docuflow

    for name in docuflow.__all__:
        assert getattr(docuflow, name) is not None


class TestDocumentPipeline:
    def test_init_with_defaults(self):
        pipeline = DocumentPipeline()
        assert pipeline._model == "openai/gpt-4o"
        assert pipeline._parser == "pdfplumber"
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
