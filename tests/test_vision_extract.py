from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from docflow.documents.models import Document, DocumentMetadata, Page
from docflow.extraction.engine import VisionExtractionEngine
from docflow.extraction.llm.base import LLMResponse
from docflow.extraction.models import ExtractionResult
from docflow.workflow.state import PipelineState
from docflow.workflow.steps import ExtractVision, PipelineStep


class Invoice(BaseModel):
    supplier_name: str
    total: float


def _make_doc(status: str = "ingested") -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
        ),
        status=status,
    )


def _make_parsed_doc() -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
        ),
        pages=[Page(page_number=0, text="some parsed text")],
        raw_text="some parsed text",
        status="parsed",
    )


def _make_llm_response() -> LLMResponse:
    data = {
        "data": {"supplier_name": "Acme Corp", "total": 1234.56},
        "evidence": {
            "supplier_name": {"page": 0, "text": "Acme Corp", "confidence": 0.95},
            "total": {"page": 0, "text": "1234.56", "confidence": 0.9},
        },
    }
    return LLMResponse(content=json.dumps(data), model="gpt-4o")


class TestExtractVisionStep:
    def test_protocol_compliance(self):
        step = ExtractVision(schema=Invoice, llm=AsyncMock())
        assert isinstance(step, PipelineStep)

    async def test_errors_if_no_document(self):
        step = ExtractVision(schema=Invoice, llm=AsyncMock())
        state = PipelineState()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "No document" in result.errors[0]

    async def test_errors_if_document_already_parsed(self):
        step = ExtractVision(schema=Invoice, llm=AsyncMock())
        state = PipelineState()
        state.document = _make_parsed_doc()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "cannot be used after a Parse step" in result.errors[0]

    async def test_errors_if_no_schema(self):
        step = ExtractVision(llm=AsyncMock())
        state = PipelineState()
        state.document = _make_doc()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "No schema" in result.errors[0]

    def test_has_same_params_as_extract(self):
        step = ExtractVision(
            schema=Invoice, llm=AsyncMock(),
            mode="multi", n_instances=3,
            temperatures=[0.1, 0.3, 0.5], dpi=300,
        )
        assert step.mode == "multi"
        assert step.n_instances == 3
        assert step.temperatures == [0.1, 0.3, 0.5]
        assert step.dpi == 300


class TestDocumentPipelineVision:
    def test_vision_with_parser_raises(self):
        from docflow.processor import DocumentPipeline

        with pytest.raises(ValueError, match="cannot be used with a parser"):
            DocumentPipeline(
                parser="pymupdf",
                extraction_type="vision",
            )

    def test_vision_with_parser_none_ok(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            parser=None,
            extraction_type="vision",
            model="openai/gpt-4o",
        )
        assert pipeline._extraction_type == "vision"

    def test_vision_with_parser_none_string_ok(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            parser="none",
            extraction_type="vision",
        )
        assert pipeline._extraction_type == "vision"

    def test_text_with_parser_ok(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            parser="pymupdf",
            extraction_type="text",
        )
        assert pipeline._extraction_type == "text"


class TestVisionExtractionEngine:
    async def test_render_fails_for_missing_file(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        engine = VisionExtractionEngine(llm=mock_llm, dpi=100)

        # pymupdf.FileNotFoundError is not a subclass of Python's FileNotFoundError
        import pymupdf

        with pytest.raises(pymupdf.FileNotFoundError):
            await engine.extract(_make_doc(), schema=Invoice)

    async def test_extract_single_mode_calls_llm_once(self):
        from unittest.mock import MagicMock

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 800
        mock_img.save = MagicMock()

        engine = VisionExtractionEngine(llm=mock_llm, dpi=100)
        engine._render_pages = AsyncMock(return_value=[mock_img])
        engine._encode_images = MagicMock(return_value=["base64data"])
        engine._enrich_document_with_ocr = AsyncMock()

        result = await engine.extract(_make_doc(), schema=Invoice, mode="single")

        assert isinstance(result, ExtractionResult)
        assert result.data["supplier_name"] == "Acme Corp"
        assert mock_llm.complete.call_count == 1
        engine._enrich_document_with_ocr.assert_called_once()

        call_messages = mock_llm.complete.call_args[0][0]
        assert call_messages[0]["role"] == "system"
        assert "page images" in call_messages[0]["content"]
        user_content = call_messages[1]["content"]
        assert isinstance(user_content, list)
        assert any(p.get("type") == "image_url" for p in user_content)

    async def test_extract_multi_mode(self):
        from unittest.mock import MagicMock

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 800
        mock_img.save = MagicMock()

        engine = VisionExtractionEngine(llm=mock_llm, dpi=100)
        engine._render_pages = AsyncMock(return_value=[mock_img])
        engine._encode_images = MagicMock(return_value=["base64data"])
        engine._enrich_document_with_ocr = AsyncMock()

        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert isinstance(result, ExtractionResult)
        # 3 candidates + 1 decider = 4
        assert mock_llm.complete.call_count == 4

    async def test_ocr_enrichment_populates_document(self):
        from unittest.mock import MagicMock

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 800
        mock_img.save = MagicMock()

        engine = VisionExtractionEngine(llm=mock_llm, dpi=100)
        engine._render_pages = AsyncMock(return_value=[mock_img])
        engine._encode_images = MagicMock(return_value=["base64data"])

        from docflow.documents.models import Block, BlockType, BoundingBox
        from docflow.ocr.base import OCRResult

        mock_ocr_result = OCRResult(
            text="Acme Corp Invoice 1234.56",
            confidence=0.92,
            blocks=[
                Block(
                    block_id="b1", block_type=BlockType.TEXT,
                    text="Acme Corp",
                    bbox=BoundingBox(x0=10, y0=20, x1=100, y1=40),
                    confidence=0.95,
                ),
            ],
        )

        with patch(
            "docflow.ocr.tesseract.TesseractOCR"
        ) as mock_ocr_cls:
            mock_ocr_instance = AsyncMock()
            mock_ocr_instance.ocr = AsyncMock(return_value=mock_ocr_result)
            mock_ocr_cls.return_value = mock_ocr_instance

            doc = _make_doc()
            await engine.extract(doc, schema=Invoice, mode="single")

        assert len(doc.pages) == 1
        assert len(doc.pages[0].blocks) == 1
        assert doc.pages[0].blocks[0].confidence == 0.95
        assert doc.pages[0].blocks[0].bbox is not None
        assert doc.raw_text != ""


class TestVisionPrompt:
    def test_build_vision_prompt(self):
        from docflow.extraction.prompts import build_vision_extraction_prompt

        messages = build_vision_extraction_prompt(Invoice, ["base64img1", "base64img2"])

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "page images" in messages[0]["content"]

        user_content = messages[1]["content"]
        assert isinstance(user_content, list)

        text_parts = [p for p in user_content if p.get("type") == "text"]
        assert len(text_parts) == 1
        assert "supplier_name" in text_parts[0]["text"]

        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 2
        assert "base64img1" in image_parts[0]["image_url"]["url"]
