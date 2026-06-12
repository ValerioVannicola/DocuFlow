from __future__ import annotations

import pytest

from docuflow.documents.locate import locate_text
from docuflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
    Word,
)


def _word(text: str, x0: float, x1: float, y: float, conf: float | None = None) -> Word:
    return Word(
        text=text,
        bbox=BoundingBox(x0=x0, y0=y, x1=x1, y1=y + 12),
        confidence=conf,
    )


def _line(block_id: str, words: list[Word]) -> Block:
    return Block(
        block_id=block_id,
        block_type=BlockType.TEXT,
        text=" ".join(w.text for w in words),
        bbox=BoundingBox(
            x0=min(w.bbox.x0 for w in words),
            y0=min(w.bbox.y0 for w in words),
            x1=max(w.bbox.x1 for w in words),
            y1=max(w.bbox.y1 for w in words),
        ),
        words=words,
    )


def _doc(pages: list[Page]) -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=pages,
        raw_text="\n\n".join(p.text for p in pages),
    )


def _page(page_number: int, blocks: list[Block]) -> Page:
    return Page(
        page_number=page_number,
        width=595,
        height=842,
        blocks=blocks,
        text="\n".join(b.text for b in blocks),
    )


@pytest.fixture
def invoice_doc() -> Document:
    return _doc([
        _page(0, [
            _line("l1", [
                _word("Invoice", 72, 120, 72, 0.99),
                _word("from", 125, 155, 72, 0.97),
                _word("Acme", 160, 200, 72, 0.93),
                _word("Corp", 205, 240, 72, 0.90),
            ]),
            _line("l2", [
                _word("Total:", 72, 110, 100, 0.97),
                _word("$1,234.56", 115, 180, 100, 0.70),
            ]),
        ]),
        _page(1, [
            _line("l3", [
                _word("Payment", 72, 130, 72, 0.95),
                _word("terms:", 135, 175, 72, 0.94),
                _word("Net", 180, 205, 72, 0.96),
                _word("30", 210, 228, 72, 0.92),
            ]),
        ]),
    ])


class TestExactMatching:
    def test_single_word_rect_is_word_bbox(self, invoice_doc):
        spans = locate_text(invoice_doc, "Acme")
        assert len(spans) == 1
        span = spans[0]
        assert span.text == "Acme"
        assert span.bbox == BoundingBox(x0=160, y0=72, x1=200, y1=84)
        assert span.confidence == 0.93
        assert span.method == "exact"

    def test_multi_word_union_and_min_confidence(self, invoice_doc):
        spans = locate_text(invoice_doc, "Acme Corp")
        span = spans[0]
        assert span.bbox.x0 == 160
        assert span.bbox.x1 == 240
        # min word confidence, not mean
        assert span.confidence == 0.90
        assert len(span.rects) == 1

    def test_currency_normalization(self, invoice_doc):
        spans = locate_text(invoice_doc, "1234.56")
        assert spans
        assert spans[0].confidence == 0.70

    def test_case_sensitive(self, invoice_doc):
        assert locate_text(invoice_doc, "acme", case_sensitive=True, fuzzy=False) == []
        assert locate_text(invoice_doc, "Acme", case_sensitive=True)

    def test_no_match(self, invoice_doc):
        assert locate_text(invoice_doc, "zzz-not-here-999") == []

    def test_find_all_across_pages(self, invoice_doc):
        spans = locate_text(invoice_doc, "Invoice", find_all=True)
        assert len(spans) == 1
        spans = locate_text(invoice_doc, "Net 30", find_all=True)
        assert spans[0].page_number == 1


class TestCrossBoundarySpans:
    def test_cross_line_span_has_one_rect_per_line(self, invoice_doc):
        # "Corp Total:" spans line l1 and line l2 on page 0
        spans = locate_text(invoice_doc, "Corp Total:")
        assert len(spans) == 1
        span = spans[0]
        assert len(span.rects) == 2
        assert span.rects[0].bbox == BoundingBox(x0=205, y0=72, x1=240, y1=84)
        assert span.rects[1].bbox == BoundingBox(x0=72, y0=100, x1=110, y1=112)
        # single page: union bbox still present
        assert span.bbox is not None
        assert span.block_ids == ["l1", "l2"]

    def test_cross_page_span(self, invoice_doc):
        # "$1,234.56 Payment" spans page 0 (l2) and page 1 (l3)
        spans = locate_text(invoice_doc, "1234.56 Payment")
        assert len(spans) == 1
        span = spans[0]
        pages = [r.page_number for r in span.rects]
        assert pages == [0, 1]
        # cross-page: no single union bbox
        assert span.bbox is None
        assert span.page_number == 0
        assert span.confidence == 0.70


class TestSeparatorInference:
    def test_tight_join_without_space(self):
        # "INV" and "-001" sit 1pt apart on the same line: they should
        # match the query "INV-001" joined without a space
        doc = _doc([
            _page(0, [
                _line("l1", [
                    _word("No:", 72, 95, 72, 0.9),
                    _word("INV", 100, 125, 72, 0.95),
                    _word("-001", 126, 155, 72, 0.85),
                ]),
            ]),
        ])
        spans = locate_text(doc, "INV-001", fuzzy=False)
        assert len(spans) == 1
        assert spans[0].confidence == 0.85
        assert spans[0].match_ratio == 1.0


class TestFuzzyMatching:
    def test_ocr_garble(self, invoice_doc):
        doc = _doc([
            _page(0, [
                _line("l1", [
                    _word("lnvoice", 72, 120, 72, 0.7),
                    _word("INV-O01", 125, 180, 72, 0.65),
                ]),
            ]),
        ])
        spans = locate_text(doc, "INV-001")
        assert len(spans) == 1
        assert spans[0].method == "fuzzy"
        assert 0.8 <= spans[0].match_ratio < 1.0
        assert spans[0].confidence == 0.65

    def test_fuzzy_disabled(self):
        doc = _doc([
            _page(0, [_line("l1", [_word("INV-O01", 72, 130, 72, 0.65)])]),
        ])
        assert locate_text(doc, "INV-001", fuzzy=False) == []


class TestHintPage:
    def test_hint_page_preferred(self):
        word_p0 = _word("Acme", 72, 110, 72, 0.9)
        word_p1 = _word("Acme", 72, 110, 72, 0.8)
        doc = _doc([
            _page(0, [_line("l1", [word_p0])]),
            _page(1, [_line("l2", [word_p1])]),
        ])
        spans = locate_text(doc, "Acme", hint_page=1)
        assert spans[0].page_number == 1
        spans = locate_text(doc, "Acme")
        assert spans[0].page_number == 0


class TestWordlessBlocks:
    def test_tokenized_fallback_uses_block_bbox(self):
        block = Block(
            block_id="b1",
            block_type=BlockType.TEXT,
            text="Supplier: Acme Corporation",
            bbox=BoundingBox(x0=72, y0=72, x1=300, y1=90),
        )
        doc = _doc([_page(0, [block])])
        spans = locate_text(doc, "Acme Corporation")
        assert len(spans) == 1
        assert spans[0].bbox == block.bbox
        assert spans[0].confidence is None


class TestRelativeCoordinates:
    def test_to_relative(self):
        bbox = BoundingBox(x0=59.5, y0=84.2, x1=297.5, y1=421.0)
        rel = bbox.to_relative(595, 842)
        assert rel.x0 == pytest.approx(0.1)
        assert rel.y0 == pytest.approx(0.1)
        assert rel.x1 == pytest.approx(0.5)
        assert rel.y1 == pytest.approx(0.5)

    def test_to_relative_invalid_dims_noop(self):
        bbox = BoundingBox(x0=10, y0=10, x1=20, y1=20)
        assert bbox.to_relative(0, 842) == bbox
