from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from docflow.documents.models import Document, DocumentMetadata, Page
from docflow.extraction.engine import HybridExtractionEngine
from docflow.extraction.llm.base import LLMResponse
from docflow.extraction.models import ExtractionResult
from docflow.ocr.base import OCRResult
from docflow.workflow.state import PipelineState
from docflow.workflow.steps import ExtractHybrid, PipelineStep


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
        pages=[Page(page_number=0, text="parsed")],
        raw_text="parsed",
        status="parsed",
    )


def _make_llm_response(supplier: str = "Acme Corp", total: float = 1234.56) -> LLMResponse:
    data = {
        "data": {"supplier_name": supplier, "total": total},
        "evidence": {
            "supplier_name": {"page": 0, "text": supplier, "confidence": 0.95},
            "total": {"page": 0, "text": str(total), "confidence": 0.9},
        },
    }
    return LLMResponse(content=json.dumps(data), model="gpt-4o")


def _mock_img():
    img = MagicMock()
    img.width = 600
    img.height = 800
    img.save = MagicMock()
    return img


def _patch_rendering_and_ocr(mock_img):
    return (
        patch(
            "docflow.rendering.renderer.render_all_pages",
            new_callable=AsyncMock, return_value=[mock_img],
        ),
        patch(
            "docflow.ocr.tesseract.TesseractOCR",
            return_value=MagicMock(
                ocr=AsyncMock(return_value=OCRResult(text="Acme Corp 1234.56", blocks=[])),
            ),
        ),
    )


class TestExtractHybridStep:
    def test_protocol_compliance(self):
        step = ExtractHybrid(schema=Invoice, llm=AsyncMock())
        assert isinstance(step, PipelineStep)

    async def test_errors_if_no_document(self):
        step = ExtractHybrid(schema=Invoice, llm=AsyncMock())
        state = PipelineState()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "No document" in result.errors[0]

    async def test_errors_if_document_already_parsed(self):
        step = ExtractHybrid(schema=Invoice, llm=AsyncMock())
        state = PipelineState()
        state.document = _make_parsed_doc()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "cannot be used after a Parse step" in result.errors[0]

    async def test_errors_if_no_schema(self):
        step = ExtractHybrid(llm=AsyncMock())
        state = PipelineState()
        state.document = _make_doc()
        result = await step.execute(state)
        assert result.status == "failed"
        assert "No schema" in result.errors[0]

    def test_params(self):
        step = ExtractHybrid(
            schema=Invoice, llm=AsyncMock(),
            n_instances=3, temperatures=[0.1, 0.3, 0.5], dpi=300,
        )
        assert step.n_instances == 3
        assert step.dpi == 300


class TestDocumentPipelineHybrid:
    def test_hybrid_with_parser_raises(self):
        from docflow.processor import DocumentPipeline

        with pytest.raises(ValueError, match="cannot be used with a parser"):
            DocumentPipeline(parser="pymupdf", extraction_type="hybrid")

    def test_hybrid_with_parser_none_ok(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser=None, extraction_type="hybrid")
        assert pipeline._extraction_type == "hybrid"


class TestHybridExtractionEngine:
    async def test_runs_vision_and_text_in_parallel(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())
        img = _mock_img()

        p_render, p_ocr = _patch_rendering_and_ocr(img)
        with p_render, p_ocr:
            engine = HybridExtractionEngine(llm=mock_llm, dpi=100)
            result = await engine.extract(_make_doc(), schema=Invoice, n_instances=2)

        assert isinstance(result, ExtractionResult)
        assert result.data["supplier_name"] == "Acme Corp"
        # 2 vision + 2 text + 1 decider = 5
        assert mock_llm.complete.call_count == 5

    async def test_n_instances_controls_split(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())
        img = _mock_img()

        p_render, p_ocr = _patch_rendering_and_ocr(img)
        with p_render, p_ocr:
            engine = HybridExtractionEngine(llm=mock_llm, dpi=100)
            await engine.extract(_make_doc(), schema=Invoice, n_instances=3)

        # 3 vision + 3 text + 1 decider = 7
        assert mock_llm.complete.call_count == 7

    async def test_handles_partial_failures(self):
        call_count = 0

        async def mock_complete(messages, temperature=0.0, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("one instance failed")
            return _make_llm_response()

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete
        img = _mock_img()

        p_render, p_ocr = _patch_rendering_and_ocr(img)
        with p_render, p_ocr:
            engine = HybridExtractionEngine(llm=mock_llm, dpi=100)
            result = await engine.extract(_make_doc(), schema=Invoice, n_instances=2)

        assert isinstance(result, ExtractionResult)

    async def test_all_fail_raises(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("all fail"))
        img = _mock_img()

        from docflow.errors import SchemaExtractionError

        p_render, p_ocr = _patch_rendering_and_ocr(img)
        with p_render, p_ocr:
            engine = HybridExtractionEngine(llm=mock_llm, dpi=100)
            with pytest.raises(SchemaExtractionError, match="All 4 hybrid"):
                await engine.extract(_make_doc(), schema=Invoice, n_instances=2)

    async def test_single_candidate_skips_decider(self):
        call_count = 0

        async def mock_complete(messages, temperature=0.0, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RuntimeError("fail")
            return _make_llm_response()

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete
        img = _mock_img()

        p_render, p_ocr = _patch_rendering_and_ocr(img)
        with p_render, p_ocr:
            engine = HybridExtractionEngine(llm=mock_llm, dpi=100)
            result = await engine.extract(_make_doc(), schema=Invoice, n_instances=2)

        assert result.data["supplier_name"] == "Acme Corp"
        assert call_count == 4


class TestHybridDeciderPrompt:
    def test_build_hybrid_decider_prompt(self):
        from docflow.extraction.engine import _build_hybrid_decider_prompt

        candidates = [
            {"data": {"supplier_name": "Acme"}, "evidence": {}},
            {"data": {"supplier_name": "Acme Corp"}, "evidence": {}},
        ]
        labels = ["vision", "text"]
        messages = _build_hybrid_decider_prompt(Invoice, candidates, labels, ["img_b64"])

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "vision" in messages[0]["content"].lower()

        user_content = messages[1]["content"]
        assert isinstance(user_content, list)

        text_parts = [p for p in user_content if p.get("type") == "text"]
        assert "vision" in text_parts[0]["text"]
        assert "text" in text_parts[0]["text"]

        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 1
