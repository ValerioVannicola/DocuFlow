from __future__ import annotations

import tempfile
from pathlib import Path

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


class TestVisionPrivacyGuard:
    def test_vision_with_privacy_raises(self):
        from docflow.processor import DocumentPipeline

        with pytest.raises(ValueError, match="bypassing"):
            DocumentPipeline(parser=None, extraction_type="vision", privacy=object())

    def test_hybrid_with_privacy_raises(self):
        from docflow.processor import DocumentPipeline

        with pytest.raises(ValueError, match="bypassing"):
            DocumentPipeline(parser=None, extraction_type="hybrid", privacy=object())

    def test_text_and_auto_with_privacy_ok(self):
        from docflow.processor import DocumentPipeline

        DocumentPipeline(extraction_type="text", privacy=object())
        DocumentPipeline(extraction_type="auto", privacy=object())


class TestPdfplumberColumnSplit:
    def test_wide_gap_splits_blocks(self):
        from docflow.parsing.pdfplumber_parser import _group_words_into_lines

        # two columns on the same visual line, 200pt apart
        words = [
            {"text": "Left", "x0": 40, "x1": 70, "top": 100, "bottom": 112},
            {"text": "column", "x0": 74, "x1": 120, "top": 100, "bottom": 112},
            {"text": "Right", "x0": 320, "x1": 355, "top": 100, "bottom": 112},
            {"text": "column", "x0": 359, "x1": 405, "top": 100, "bottom": 112},
        ]
        lines = _group_words_into_lines(words)
        assert len(lines) == 2
        assert [w["text"] for w in lines[0]] == ["Left", "column"]
        assert [w["text"] for w in lines[1]] == ["Right", "column"]

    def test_normal_spacing_stays_together(self):
        from docflow.parsing.pdfplumber_parser import _group_words_into_lines

        words = [
            {"text": "Total:", "x0": 40, "x1": 75, "top": 100, "bottom": 112},
            {"text": "1234.56", "x0": 80, "x1": 130, "top": 100, "bottom": 112},
        ]
        lines = _group_words_into_lines(words)
        assert len(lines) == 1


class TestMixedDocumentScoring:
    def test_native_page_span_scores_none_not_zero(self):
        """In a smart-parsed doc mixing OCR and native pages, a field matched
        on a native page must not report score 0.0 (looks like terrible OCR)."""
        from docflow.extraction.scoring import compute_field_ocr_confidence

        ocr_word = Word(
            text="scanned", bbox=BoundingBox(x0=0, y0=0, x1=50, y1=12),
            confidence=0.9,
        )
        native_word = Word(
            text="1234.56", bbox=BoundingBox(x0=0, y0=0, x1=50, y1=12),
            confidence=None,
        )
        doc = Document(
            id="d1",
            metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
            pages=[
                Page(page_number=0, text="scanned",
                     blocks=[Block(block_id="b1", text="scanned",
                                   confidence=0.9, words=[ocr_word])]),
                Page(page_number=1, text="Total: 1234.56",
                     blocks=[Block(block_id="b2", text="1234.56",
                                   words=[native_word])]),
            ],
            raw_text="scanned\n\nTotal: 1234.56",
        )
        result = compute_field_ocr_confidence(doc, "1234.56")
        assert result is not None
        assert result.match_method == "exact_block"
        assert result.score is None  # not 0.0


class TestExactPreferredOverFuzzy:
    def test_exact_value_match_beats_fuzzy_hint_match(self):
        from docflow.extraction.scoring import compute_field_ocr_confidence

        def line(block_id, text, confs):
            words = [
                Word(text=t, bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10), confidence=c)
                for t, c in zip(text.split(), confs, strict=True)
            ]
            return Block(block_id=block_id, text=text,
                         confidence=sum(confs) / len(confs), words=words)

        doc = Document(
            id="d1",
            metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
            pages=[Page(
                page_number=0,
                text="Ref: INV-O01\nNumber: INV-001",
                blocks=[
                    line("b1", "Ref: INV-O01", [0.9, 0.5]),
                    line("b2", "Number: INV-001", [0.9, 0.95]),
                ],
            )],
            raw_text="Ref: INV-O01\nNumber: INV-001",
        )
        # hint is garbled (fuzzy match), value matches exactly elsewhere
        result = compute_field_ocr_confidence(doc, "INV-001", hint_text="INV-OO1")
        assert result is not None
        assert result.match_method == "exact_block"
        assert result.score == pytest.approx(0.95)


class TestDockerizeDependencies:
    def _generate(self, config_yaml: str) -> tuple[str, str]:
        from docflow.dockerize import generate_deployment

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "workflow.yaml"
            cfg.write_text(config_yaml)
            out = generate_deployment(cfg, Path(tmp) / "deploy")
            return (
                (out / "requirements.txt").read_text(),
                (out / "Dockerfile").read_text(),
            )

    def test_smart_parser_gets_ocr_and_tesseract_binary(self):
        reqs, dockerfile = self._generate(
            "name: t\nschema:\n  total: {type: float}\nparser: smart\n"
        )
        assert "ocr" in reqs
        assert "pdf" in reqs
        assert "tesseract-ocr" in dockerfile

    def test_pdfplumber_parser_skips_tesseract(self):
        reqs, dockerfile = self._generate(
            "name: t\nschema:\n  total: {type: float}\nparser: pdfplumber\n"
        )
        assert "tesseract-ocr" not in dockerfile
        assert "pdf" in reqs

    def test_cloud_parser_gets_sdk_extra(self):
        reqs, _ = self._generate(
            "name: t\nschema:\n  total: {type: float}\nparser: azure-di\n"
        )
        assert "azure" in reqs

    def test_auto_extraction_gets_vision_deps(self):
        reqs, dockerfile = self._generate(
            "name: t\nschema:\n  total: {type: float}\nextraction_type: auto\n"
        )
        assert "ocr" in reqs
        assert "tesseract-ocr" in dockerfile


class TestWordPreciseRedaction:
    async def test_redacts_only_matching_words(self):
        from unittest.mock import AsyncMock

        from docflow.ocr.base import OCRResult
        from docflow.privacy.image_redaction import ImageRedactor
        from docflow.privacy.models import PrivacyFinding

        words = [
            Word(text="Contact", bbox=BoundingBox(x0=10, y0=20, x1=60, y1=32)),
            Word(text="John", bbox=BoundingBox(x0=65, y0=20, x1=95, y1=32)),
            Word(text="Doe", bbox=BoundingBox(x0=100, y0=20, x1=125, y1=32)),
            Word(text="today", bbox=BoundingBox(x0=130, y0=20, x1=165, y1=32)),
        ]
        block = Block(
            block_id="b1", block_type=BlockType.TEXT,
            text="Contact John Doe today",
            bbox=BoundingBox(x0=10, y0=20, x1=165, y1=32),
            words=words,
        )

        ocr = AsyncMock()
        ocr.ocr = AsyncMock(
            return_value=OCRResult(text="Contact John Doe today", blocks=[block])
        )

        provider = AsyncMock()
        # "John Doe" spans chars 8-16 of the block text
        provider.adetect_text = AsyncMock(return_value=[
            PrivacyFinding(entity_type="PERSON", start=8, end=16,
                           text="John Doe", score=0.95),
        ])

        from PIL import Image

        img = Image.new("RGB", (200, 60), "white")
        redactor = ImageRedactor(provider, ocr_engine=ocr)
        redacted, findings = await redactor.redact_page_image(img)

        assert len(findings) == 1
        bbox = findings[0].bbox
        # covers "John" through "Doe", not "Contact" or "today"
        assert bbox.x0 == 65
        assert bbox.x1 == 125
        # the pixel under "Contact" stays white; under "John" goes black
        assert redacted.getpixel((30, 26)) == (255, 255, 255)
        assert redacted.getpixel((80, 26)) == (0, 0, 0)
