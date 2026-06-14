from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from docuflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
)
from docuflow.extraction.engine import ExtractionEngine
from docuflow.extraction.llm.base import LLMResponse
from docuflow.extraction.models import ExtractionResult


class Invoice(BaseModel):
    supplier_name: str
    invoice_number: str
    total: float


def _make_document() -> Document:
    return Document(
        id="doc-test-123",
        metadata=DocumentMetadata(
            file_name="test.pdf",
            file_path="C:/test/test.pdf",
            mime_type="application/pdf",
        ),
        pages=[
            Page(
                page_number=0,
                width=595,
                height=842,
                text="Invoice from Acme Corp\nInvoice #: INV-001\nTotal: 1234.56",
                blocks=[
                    Block(
                        block_id="b1",
                        block_type=BlockType.TEXT,
                        text="Invoice from Acme Corp",
                        bbox=BoundingBox(x0=72, y0=72, x1=300, y1=90),
                    ),
                    Block(
                        block_id="b2",
                        block_type=BlockType.TEXT,
                        text="Invoice #: INV-001",
                        bbox=BoundingBox(x0=72, y0=100, x1=300, y1=118),
                    ),
                    Block(
                        block_id="b3",
                        block_type=BlockType.TEXT,
                        text="Total: 1234.56",
                        bbox=BoundingBox(x0=72, y0=130, x1=300, y1=148),
                    ),
                ],
            )
        ],
        raw_text="Invoice from Acme Corp\nInvoice #: INV-001\nTotal: 1234.56",
    )


class TestExtractionEngine:
    async def test_extract_success(self):
        llm_response_data = {
            "data": {
                "supplier_name": "Acme Corp",
                "invoice_number": "INV-001",
                "total": 1234.56,
            },
            "evidence": {
                "supplier_name": {"page": 0, "text": "Acme Corp"},
                "invoice_number": {"page": 0, "text": "INV-001"},
                "total": {"page": 0, "text": "1234.56"},
            },
        }

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps(llm_response_data),
                model="gpt-4o",
                usage={"prompt_tokens": 500, "completion_tokens": 100},
            )
        )

        engine = ExtractionEngine(llm=mock_llm)
        doc = _make_document()
        result = await engine.extract(doc, schema=Invoice)

        assert isinstance(result, ExtractionResult)
        assert result.document_id == "doc-test-123"
        assert result.schema_name == "Invoice"
        assert result.data["supplier_name"] == "Acme Corp"
        assert result.data["total"] == 1234.56
        assert "supplier_name" in result.fields
        assert result.fields["supplier_name"].value == "Acme Corp"
        assert len(result.fields["supplier_name"].evidence) > 0

    async def test_extract_with_evidence_matching(self):
        llm_response_data = {
            "data": {
                "supplier_name": "Acme Corp",
                "invoice_number": "INV-001",
                "total": 1234.56,
            },
            "evidence": {
                "supplier_name": {"page": 0, "text": "Acme Corp"},
                "total": {"page": 0, "text": "1234.56"},
            },
        }

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=json.dumps(llm_response_data), model="gpt-4o")
        )

        engine = ExtractionEngine(llm=mock_llm)
        doc = _make_document()
        result = await engine.extract(doc, schema=Invoice)

        supplier_evidence = result.fields["supplier_name"].evidence
        assert len(supplier_evidence) > 0
        assert supplier_evidence[0].text == "Acme Corp"

    async def test_extract_invalid_json(self):
        from docuflow.errors import SchemaExtractionError

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content="not valid json", model="gpt-4o")
        )

        engine = ExtractionEngine(llm=mock_llm)
        doc = _make_document()

        with pytest.raises(SchemaExtractionError, match="parse LLM response"):
            await engine.extract(doc, schema=Invoice)

    async def test_extract_schema_mismatch(self):
        from docuflow.errors import SchemaExtractionError

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({"data": {"wrong_field": "value"}}),
                model="gpt-4o",
            )
        )

        engine = ExtractionEngine(llm=mock_llm)
        doc = _make_document()

        with pytest.raises(SchemaExtractionError, match="does not match schema"):
            await engine.extract(doc, schema=Invoice)


class TestConfidenceScores:
    def _ocr_document(self) -> Document:
        from docuflow.documents.models import Word

        def line(block_id, text, confs, y):
            words = [
                Word(
                    text=t,
                    bbox=BoundingBox(x0=72, y0=y, x1=300, y1=y + 18),
                    confidence=c,
                )
                for t, c in zip(text.split(), confs, strict=True)
            ]
            return Block(
                block_id=block_id,
                block_type=BlockType.TEXT,
                text=text,
                bbox=BoundingBox(x0=72, y0=y, x1=300, y1=y + 18),
                confidence=sum(confs) / len(confs),
                words=words,
            )

        doc = _make_document()
        doc.pages[0].blocks = [
            line("b1", "Invoice from Acme Corp", [0.99, 0.97, 0.93, 0.9], 72),
            line("b2", "Invoice #: INV-001", [0.98, 0.95, 0.85], 100),
            line("b3", "Total: 1234.56", [0.97, 0.7], 130),
        ]
        return doc

    def _llm_response(self) -> str:
        return json.dumps({
            "data": {
                "supplier_name": "Acme Corp",
                "invoice_number": "INV-001",
                "total": 1234.56,
            },
            "evidence": {
                "supplier_name": {"page": 0, "text": "Acme Corp"},
                "invoice_number": {"page": 0, "text": "INV-001"},
                "total": {"page": 0, "text": "1234.56"},
            },
        })

    async def test_ocr_scores_populated_for_ocr_document(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=self._llm_response(), model="gpt-4o")
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(self._ocr_document(), schema=Invoice)

        assert result.ocr is not None
        assert result.ocr.word_count == 9
        assert 0 < result.ocr.score <= 1

        total = result.fields["total"]
        assert total.ocr is not None
        assert total.ocr.match_method == "exact_block"
        assert total.ocr.score == 0.7

        supplier = result.fields["supplier_name"]
        assert supplier.ocr is not None
        # min word confidence of the matched span "Acme Corp"
        assert supplier.ocr.score == 0.9

    async def test_ocr_scores_none_without_ocr(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=self._llm_response(), model="gpt-4o")
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(_make_document(), schema=Invoice)

        assert result.ocr is None
        assert all(f.ocr is None for f in result.fields.values())

    async def test_consensus_none_for_single_instance(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=self._llm_response(), model="gpt-4o")
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(_make_document(), schema=Invoice)

        assert all(f.consensus is None for f in result.fields.values())

    async def test_consensus_populated_in_multi_mode(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=self._llm_response(), model="gpt-4o")
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_document(), schema=Invoice, mode="multi", n_instances=3,
        )

        total = result.fields["total"]
        assert total.consensus is not None
        assert total.consensus.n_instances == 3
        assert total.consensus.agreement == "3/3"
        assert total.consensus.agreement_ratio == 1.0


class TestPrompts:
    def test_build_extraction_prompt(self):
        from docuflow.extraction.prompts import build_extraction_prompt

        messages = build_extraction_prompt(Invoice, "Test document text")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "supplier_name" in messages[1]["content"]
        assert "Test document text" in messages[1]["content"]

    def test_prompt_with_pages(self):
        from docuflow.extraction.prompts import build_extraction_prompt

        messages = build_extraction_prompt(
            Invoice, "full text", page_texts=["Page 0 text", "Page 1 text"]
        )
        assert "Page 0" in messages[1]["content"]
        assert "Page 1" in messages[1]["content"]

    def test_build_extraction_prompt_preserves_source_text_by_default(self):
        from docuflow.extraction.prompts import build_extraction_prompt

        messages = build_extraction_prompt(Invoice, "Test document text")
        assert "Preserve the exact source text" in messages[0]["content"]
        assert "Do not convert dates to ISO" in messages[0]["content"]

    def test_build_extraction_prompt_can_normalize_output(self):
        from docuflow.extraction.prompts import build_extraction_prompt

        messages = build_extraction_prompt(
            Invoice, "Test document text", normalize_output=True
        )
        assert "you may normalize it to a canonical form" in messages[0]["content"]
