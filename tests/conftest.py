from __future__ import annotations

import uuid

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

_PAGE_SIZE = (595, 842)


def make_test_pdf(path, texts: list[tuple[float, float, str]] | None = None, pages: int = 1) -> None:
    """Create a PDF fixture with reportlab. `texts` are (x, y-from-top, text)."""
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed for test PDF creation")

    c = canvas.Canvas(str(path), pagesize=_PAGE_SIZE)
    for page_index in range(pages):
        if page_index == 0:
            for x, y, text in texts or []:
                c.drawString(x, _PAGE_SIZE[1] - y, text)
        c.showPage()
    c.save()


@pytest.fixture
def sample_bbox() -> BoundingBox:
    return BoundingBox(x0=10.0, y0=20.0, x1=100.0, y1=40.0)


@pytest.fixture
def sample_block(sample_bbox: BoundingBox) -> Block:
    return Block(
        block_id="block-001",
        block_type=BlockType.TEXT,
        text="Invoice Total: €1,234.56",
        bbox=sample_bbox,
        confidence=0.95,
    )


@pytest.fixture
def sample_page(sample_block: Block) -> Page:
    return Page(
        page_number=0,
        width=595.0,
        height=842.0,
        blocks=[sample_block],
        text="Invoice Total: €1,234.56",
    )


@pytest.fixture
def sample_metadata() -> DocumentMetadata:
    return DocumentMetadata(
        file_name="test_invoice.pdf",
        file_path="C:/test_data/test_invoice.pdf",
        file_size=12345,
        file_hash="abc123",
        mime_type="application/pdf",
        page_count=1,
    )


@pytest.fixture
def sample_document(sample_metadata: DocumentMetadata, sample_page: Page) -> Document:
    return Document(
        id=str(uuid.uuid4()),
        metadata=sample_metadata,
        pages=[sample_page],
        raw_text="Invoice Total: €1,234.56",
        status="parsed",
    )


@pytest.fixture
def sample_evidence(sample_document: Document, sample_bbox: BoundingBox) -> Evidence:
    return Evidence(
        document_id=sample_document.id,
        page_number=0,
        text="€1,234.56",
        bbox=sample_bbox,
        block_id="block-001",
        confidence=0.95,
    )


@pytest.fixture
def sample_extracted_field(sample_evidence: Evidence) -> ExtractedField:
    return ExtractedField(
        value=1234.56,
        confidence=0.92,
        evidence=[sample_evidence],
        validation_status="valid",
    )


@pytest.fixture
def sample_extraction_result(
    sample_document: Document,
    sample_extracted_field: ExtractedField,
) -> ExtractionResult:
    return ExtractionResult(
        document_id=sample_document.id,
        schema_name="Invoice",
        data={"total": 1234.56, "supplier_name": "Acme Corp"},
        fields={"total": sample_extracted_field},
        confidence=0.92,
        trace_id=str(uuid.uuid4()),
    )
