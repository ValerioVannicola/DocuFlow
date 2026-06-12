from __future__ import annotations

import pytest

from docflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
    Word,
)
from docflow.extraction.scoring import (
    compute_document_ocr_confidence,
    compute_field_consensus,
    compute_field_ocr_confidence,
)


def _word(text: str, conf: float | None) -> Word:
    return Word(
        text=text,
        bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        confidence=conf,
    )


def _line(text: str, confs: list[float | None]) -> Block:
    words = [_word(t, c) for t, c in zip(text.split(), confs, strict=True)]
    valid = [c for c in confs if c is not None]
    return Block(
        block_id=f"line-{text[:10]}",
        block_type=BlockType.TEXT,
        text=text,
        confidence=sum(valid) / len(valid) if valid else None,
        words=words,
    )


def _make_document(blocks: list[Block], page_text: str = "") -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=[
            Page(
                page_number=0,
                blocks=blocks,
                text=page_text or "\n".join(b.text for b in blocks),
            )
        ],
        raw_text=page_text or "\n".join(b.text for b in blocks),
    )


class TestDocumentOCRConfidence:
    def test_no_ocr_returns_none(self):
        doc = _make_document(
            [Block(block_id="b1", text="Native PDF text")]
        )
        assert compute_document_ocr_confidence(doc) is None

    def test_aggregates_word_confidences(self):
        doc = _make_document(
            [
                _line("Acme Corp", [0.9, 0.8]),
                _line("Total: 100", [0.95, 0.55]),
            ]
        )
        result = compute_document_ocr_confidence(doc)
        assert result is not None
        assert result.word_count == 4
        assert result.score == pytest.approx(0.8)
        assert result.low_confidence_ratio == pytest.approx(0.25)

    def test_block_confidence_fallback_without_words(self):
        doc = _make_document(
            [
                Block(block_id="b1", text="Line one", confidence=0.9),
                Block(block_id="b2", text="Line two", confidence=0.7),
            ]
        )
        result = compute_document_ocr_confidence(doc)
        assert result is not None
        assert result.score == pytest.approx(0.8)
        assert result.word_count == 2


class TestFieldOCRConfidence:
    def test_no_ocr_returns_none(self):
        doc = _make_document([Block(block_id="b1", text="Native text")])
        assert compute_field_ocr_confidence(doc, "Native") is None

    def test_exact_match_single_word(self):
        doc = _make_document([_line("Total: 1234.56", [0.95, 0.82])])
        result = compute_field_ocr_confidence(doc, 1234.56)
        assert result is not None
        assert result.match_method == "exact_block"
        assert result.score == pytest.approx(0.82)
        assert result.match_ratio == 1.0

    def test_multi_word_value_min_confidence(self):
        doc = _make_document(
            [_line("Supplier: Acme Corporation Ltd", [0.99, 0.95, 0.6, 0.9])]
        )
        result = compute_field_ocr_confidence(doc, "Acme Corporation Ltd")
        assert result is not None
        assert result.match_method == "exact_block"
        # min word confidence in the matched span, not the line mean
        assert result.score == pytest.approx(0.6)

    def test_fuzzy_match_ocr_garble(self):
        doc = _make_document([_line("lnvoice INV-O01", [0.7, 0.65])])
        result = compute_field_ocr_confidence(doc, "INV-001")
        assert result is not None
        assert result.match_method == "fuzzy_block"
        assert result.score == pytest.approx(0.65)
        assert 0.8 <= result.match_ratio < 1.0

    def test_currency_normalization(self):
        doc = _make_document([_line("Total: $1,234.56", [0.9, 0.85])])
        result = compute_field_ocr_confidence(doc, "1234.56")
        assert result is not None
        assert result.match_method == "exact_block"

    def test_unmatched_value(self):
        doc = _make_document([_line("Completely different text", [0.9, 0.9, 0.9])])
        result = compute_field_ocr_confidence(doc, "zzz-not-here-999")
        assert result is not None
        assert result.match_method == "unmatched"
        assert result.score is None

    def test_evidence_hint_preferred(self):
        doc = _make_document(
            [
                _line("Date: 15 Jan 2024", [0.9, 0.88, 0.91, 0.86]),
            ]
        )
        # value is reformatted, hint is the verbatim source quote
        result = compute_field_ocr_confidence(
            doc, "2024-01-15", hint_text="15 Jan 2024",
        )
        assert result is not None
        assert result.match_method == "exact_block"

    def test_page_text_fallback(self):
        block = _line("some other line", [0.8, 0.8, 0.8])
        doc = _make_document([block], page_text="some other line\nACME-REF-42")
        result = compute_field_ocr_confidence(doc, "ACME-REF-42")
        assert result is not None
        assert result.match_method == "page_text"
        assert result.score == pytest.approx(0.8)

    def test_none_value_no_hint(self):
        doc = _make_document([_line("Some text", [0.9, 0.9])])
        result = compute_field_ocr_confidence(doc, None)
        assert result is not None
        assert result.match_method == "unmatched"


class TestFieldConsensus:
    def _candidates(self, values: list[object]) -> list[dict]:
        return [{"data": {"total": v}} for v in values]

    def test_unanimous(self):
        c = self._candidates([100.0, 100.0, 100.0])
        result = compute_field_consensus(100.0, "total", c, n_instances=3)
        assert result.agreement == "3/3"
        assert result.agreement_ratio == 1.0
        assert result.majority_ratio == 1.0

    def test_agreement_vs_final_value(self):
        # decider overrode the majority: final=200, majority voted 100
        c = self._candidates([100.0, 100.0, 200.0])
        result = compute_field_consensus(200.0, "total", c, n_instances=3)
        assert result.agreement == "1/3"
        assert result.agreement_ratio == pytest.approx(1 / 3, abs=1e-4)
        assert result.majority_ratio == pytest.approx(2 / 3, abs=1e-4)

    def test_normalized_comparison(self):
        c = self._candidates(["$1,234.56", "1234.56"])
        result = compute_field_consensus("1234.56", "total", c, n_instances=2)
        assert result.agreement_ratio == 1.0

    def test_field_missing_from_candidates(self):
        c = [{"data": {"other": 1}}, {"data": {"other": 2}}]
        result = compute_field_consensus(100.0, "total", c, n_instances=2)
        assert result.agreement == "0/2"
        assert result.agreement_ratio == 0.0
        assert result.n_succeeded == 2

    def test_missing_field_counts_as_disagreement(self):
        # 2 of 3 candidates produced the field and agree; the third omitted
        # it — that is NOT unanimity
        c = [
            {"data": {"total": 100.0}},
            {"data": {"total": 100.0}},
            {"data": {"other": 1}},
        ]
        result = compute_field_consensus(100.0, "total", c, n_instances=3)
        assert result.agreement == "2/3"
        assert result.agreement_ratio == pytest.approx(2 / 3, abs=1e-4)
