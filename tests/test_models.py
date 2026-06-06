from __future__ import annotations

import pydantic
import pytest

from docflow.documents.evidence import Evidence
from docflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
)
from docflow.extraction.models import ExtractedField, ExtractionResult
from docflow.observability.traces import TraceEvent, create_trace


class TestBoundingBox:
    def test_create(self):
        bbox = BoundingBox(x0=0, y0=0, x1=100, y1=50)
        assert bbox.width == 100.0
        assert bbox.height == 50.0

    def test_frozen(self):
        bbox = BoundingBox(x0=0, y0=0, x1=100, y1=50)
        with pytest.raises(pydantic.ValidationError):
            bbox.x0 = 10

    def test_json_roundtrip(self):
        bbox = BoundingBox(x0=1.5, y0=2.5, x1=10.5, y1=20.5)
        data = bbox.model_dump_json()
        restored = BoundingBox.model_validate_json(data)
        assert restored == bbox


class TestBlock:
    def test_create_with_defaults(self):
        block = Block(block_id="b1")
        assert block.block_type == BlockType.TEXT
        assert block.text == ""
        assert block.bbox is None

    def test_create_with_bbox(self, sample_bbox):
        block = Block(block_id="b1", text="hello", bbox=sample_bbox)
        assert block.text == "hello"
        assert block.bbox.width == 90.0

    def test_block_types(self):
        for bt in BlockType:
            block = Block(block_id="b1", block_type=bt)
            assert block.block_type == bt


class TestPage:
    def test_create(self, sample_block):
        page = Page(page_number=0, blocks=[sample_block], text="test")
        assert page.block_count == 1
        assert page.page_number == 0

    def test_empty_page(self):
        page = Page(page_number=1)
        assert page.block_count == 0
        assert page.text == ""


class TestDocumentMetadata:
    def test_create(self, sample_metadata):
        assert sample_metadata.file_name == "test_invoice.pdf"
        assert sample_metadata.mime_type == "application/pdf"
        assert sample_metadata.page_count == 1

    def test_defaults(self):
        meta = DocumentMetadata(file_name="test.pdf", file_path="C:/test_data/test.pdf")
        assert meta.file_size == 0
        assert meta.mime_type == ""
        assert meta.extra == {}


class TestDocument:
    def test_create(self, sample_document):
        assert sample_document.status == "parsed"
        assert len(sample_document.pages) == 1
        assert sample_document.raw_text != ""

    def test_json_roundtrip(self, sample_document):
        data = sample_document.model_dump_json()
        restored = Document.model_validate_json(data)
        assert restored.id == sample_document.id
        assert restored.metadata.file_name == sample_document.metadata.file_name
        assert len(restored.pages) == len(sample_document.pages)


class TestEvidence:
    def test_create(self, sample_evidence):
        assert sample_evidence.page_number == 0
        assert sample_evidence.text == "€1,234.56"
        assert sample_evidence.confidence == 0.95

    def test_frozen(self, sample_evidence):
        with pytest.raises(pydantic.ValidationError):
            sample_evidence.text = "changed"

    def test_minimal(self):
        ev = Evidence(document_id="doc-1", page_number=0, text="test")
        assert ev.bbox is None
        assert ev.block_id is None
        assert ev.confidence is None


class TestExtractedField:
    def test_create(self, sample_extracted_field):
        assert sample_extracted_field.value == 1234.56
        assert sample_extracted_field.confidence == 0.92
        assert len(sample_extracted_field.evidence) == 1
        assert sample_extracted_field.validation_status == "valid"

    def test_defaults(self):
        field = ExtractedField()
        assert field.value is None
        assert field.confidence == 0.0
        assert field.evidence == []
        assert field.validation_status == "pending"
        assert field.errors == []

    def test_string_value(self):
        field = ExtractedField(value="Acme Corp", confidence=0.88)
        assert field.value == "Acme Corp"


class TestExtractionResult:
    def test_create(self, sample_extraction_result):
        assert sample_extraction_result.schema_name == "Invoice"
        assert sample_extraction_result.confidence == 0.92
        assert not sample_extraction_result.needs_review
        assert "total" in sample_extraction_result.fields

    def test_json_roundtrip(self, sample_extraction_result):
        data = sample_extraction_result.model_dump_json()
        restored = ExtractionResult.model_validate_json(data)
        assert restored.document_id == sample_extraction_result.document_id
        assert restored.schema_name == sample_extraction_result.schema_name

    def test_defaults(self):
        result = ExtractionResult(document_id="doc-1", schema_name="Test")
        assert result.data == {}
        assert result.fields == {}
        assert result.confidence == 0.0
        assert not result.needs_review


class TestTrace:
    def test_create(self):
        trace = create_trace("doc-1")
        assert trace.document_id == "doc-1"
        assert trace.trace_id != ""
        assert trace.events == []
        assert trace.completed_at is None

    def test_add_event(self):
        trace = create_trace("doc-1")
        trace.add_event("parsing", step_name="PyMuPDFParser", duration_ms=150.0)
        assert len(trace.events) == 1
        assert trace.events[0].event_type == "parsing"
        assert trace.events[0].step_name == "PyMuPDFParser"
        assert trace.events[0].duration_ms == 150.0

    def test_complete(self):
        trace = create_trace("doc-1")
        trace.complete()
        assert trace.completed_at is not None

    def test_event_json_roundtrip(self):
        event = TraceEvent(event_type="extraction", step_name="LLM", duration_ms=2000.0)
        data = event.model_dump_json()
        restored = TraceEvent.model_validate_json(data)
        assert restored.event_type == event.event_type
