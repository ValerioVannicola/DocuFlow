from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from docflow.documents.models import Document, DocumentMetadata, Page
from docflow.extraction.engine import ExtractionEngine, _generate_temperatures
from docflow.extraction.llm.base import LLMResponse
from docflow.extraction.models import ExtractionResult


class Invoice(BaseModel):
    supplier_name: str
    total: float


def _make_doc() -> Document:
    return Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
        ),
        pages=[Page(page_number=0, text="Invoice from Acme Corp\nTotal: 1234.56")],
        raw_text="Invoice from Acme Corp\nTotal: 1234.56",
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


class TestGenerateTemperatures:
    def test_single(self):
        temps = _generate_temperatures(1)
        assert len(temps) == 1
        assert temps[0] == 0.3

    def test_five(self):
        temps = _generate_temperatures(5)
        assert len(temps) == 5
        assert all(0.0 <= t <= 1.0 for t in temps)
        assert temps[0] < temps[-1]

    def test_three(self):
        temps = _generate_temperatures(3, mean=0.4, spread=0.2)
        assert len(temps) == 3
        assert temps[0] == pytest.approx(0.2, abs=0.01)
        assert temps[1] == pytest.approx(0.4, abs=0.01)
        assert temps[2] == pytest.approx(0.6, abs=0.01)


class TestSingleExtract:
    async def test_single_mode_default(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(_make_doc(), schema=Invoice)

        assert isinstance(result, ExtractionResult)
        assert result.data["supplier_name"] == "Acme Corp"
        assert result.data["total"] == 1234.56
        mock_llm.complete.assert_called_once()


class TestMultiExtract:
    async def test_multi_mode_runs_n_instances(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert isinstance(result, ExtractionResult)
        assert result.data["supplier_name"] == "Acme Corp"
        # 3 candidate calls + 1 decider call = 4 total
        assert mock_llm.complete.call_count == 4

    async def test_multi_mode_custom_temperatures(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice,
            mode="multi", n_instances=3, temperatures=[0.0, 0.3, 0.7],
        )

        assert isinstance(result, ExtractionResult)
        calls = mock_llm.complete.call_args_list
        candidate_temps = [c.kwargs.get("temperature", c.args[1] if len(c.args) > 1 else None)
                          for c in calls[:3]]
        assert 0.0 in candidate_temps

    async def test_multi_mode_handles_partial_failures(self):
        call_count = 0

        async def mock_complete(messages, temperature=0.0, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("one instance failed")
            return _make_llm_response()

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert isinstance(result, ExtractionResult)
        assert result.data["supplier_name"] == "Acme Corp"

    async def test_multi_mode_all_fail_raises(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("all fail"))

        engine = ExtractionEngine(llm=mock_llm)
        from docflow.errors import SchemaExtractionError

        with pytest.raises(SchemaExtractionError, match="All 3 extraction instances failed"):
            await engine.extract(
                _make_doc(), schema=Invoice, mode="multi", n_instances=3,
            )

    async def test_multi_mode_single_success_skips_decider(self):
        call_count = 0

        async def mock_complete(messages, temperature=0.0, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("fail")
            return _make_llm_response()

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert result.data["supplier_name"] == "Acme Corp"
        # 3 candidate calls (2 failed, 1 success) + no decider = 3 total
        assert call_count == 3

    async def test_multi_with_disagreement(self):
        responses = [
            _make_llm_response("Acme Corp", 1234.56),
            _make_llm_response("Acme Corp", 1234.56),
            _make_llm_response("Acme Inc", 1234.00),
        ]
        call_idx = 0

        async def mock_complete(messages, temperature=0.0, **kwargs):
            nonlocal call_idx
            if call_idx < len(responses):
                resp = responses[call_idx]
                call_idx += 1
                return resp
            return _make_llm_response("Acme Corp", 1234.56)

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert isinstance(result, ExtractionResult)
        assert "supplier_name" in result.data
