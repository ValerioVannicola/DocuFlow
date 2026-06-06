from __future__ import annotations

from docflow.documents.models import Block, BlockType, BoundingBox, Document, DocumentMetadata, Page
from docflow.search import search_document


def _make_doc() -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
        ),
        pages=[
            Page(
                page_number=0,
                text="Invoice from Acme Corp\nInvoice Number: INV-001\nTotal: 1234.56",
                blocks=[
                    Block(
                        block_id="b1", block_type=BlockType.TEXT,
                        text="Invoice from Acme Corp",
                        bbox=BoundingBox(x0=72, y0=72, x1=300, y1=90),
                    ),
                    Block(
                        block_id="b2", block_type=BlockType.TEXT,
                        text="Invoice Number: INV-001",
                        bbox=BoundingBox(x0=72, y0=100, x1=300, y1=118),
                    ),
                    Block(
                        block_id="b3", block_type=BlockType.TEXT,
                        text="Total: 1234.56",
                        bbox=BoundingBox(x0=72, y0=130, x1=200, y1=148),
                    ),
                ],
            ),
            Page(
                page_number=1,
                text="Payment terms: Net 30\nBank: Acme Bank",
                blocks=[
                    Block(
                        block_id="b4", block_type=BlockType.TEXT,
                        text="Payment terms: Net 30",
                        bbox=BoundingBox(x0=72, y0=72, x1=300, y1=90),
                    ),
                    Block(
                        block_id="b5", block_type=BlockType.TEXT,
                        text="Bank: Acme Bank",
                        bbox=BoundingBox(x0=72, y0=100, x1=200, y1=118),
                    ),
                ],
            ),
        ],
        raw_text="Invoice from Acme Corp\nTotal: 1234.56\nPayment terms: Net 30",
    )


class TestSearchDocument:
    def test_basic_search(self):
        doc = _make_doc()
        result = search_document(doc, "Acme")
        assert result.total_hits >= 1
        assert result.hits[0].text == "Acme"
        assert result.hits[0].page_number == 0

    def test_search_with_bbox(self):
        doc = _make_doc()
        result = search_document(doc, "INV-001")
        assert result.total_hits >= 1
        hit = result.hits[0]
        assert hit.bbox is not None
        assert hit.block_id == "b2"

    def test_search_across_pages(self):
        doc = _make_doc()
        result = search_document(doc, "Acme")
        pages = {h.page_number for h in result.hits}
        assert 0 in pages
        assert 1 in pages

    def test_case_insensitive(self):
        doc = _make_doc()
        result = search_document(doc, "acme")
        assert result.total_hits >= 1

    def test_case_sensitive(self):
        doc = _make_doc()
        result = search_document(doc, "acme", case_sensitive=True)
        assert result.total_hits == 0

        result = search_document(doc, "Acme", case_sensitive=True)
        assert result.total_hits >= 1

    def test_no_match(self):
        doc = _make_doc()
        result = search_document(doc, "NonExistent")
        assert result.total_hits == 0
        assert result.hits == []

    def test_empty_query(self):
        doc = _make_doc()
        result = search_document(doc, "")
        assert result.total_hits == 0

    def test_context_included(self):
        doc = _make_doc()
        result = search_document(doc, "1234.56")
        assert result.total_hits >= 1
        assert "Total" in result.hits[0].context

    def test_numeric_search(self):
        doc = _make_doc()
        result = search_document(doc, "1234.56")
        assert result.total_hits >= 1

    def test_query_in_result(self):
        doc = _make_doc()
        result = search_document(doc, "Net 30")
        assert result.query == "Net 30"
