from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from docuflow.documents.models import Document, DocumentMetadata, Page
from docuflow.extraction.engine import ExtractionEngine, _generate_temperatures
from docuflow.extraction.llm.base import LLMResponse
from docuflow.extraction.models import ExtractionResult


class Invoice(BaseModel):
    supplier_name: str
    total: float


class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    tax_rate: float | None = None
    amount: float


class DetailedInvoice(BaseModel):
    tax_rate: float | None = None
    line_items: list[LineItem] | None = None


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


class TestConsensusShortCircuit:
    async def test_unanimous_candidates_skip_decider(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert mock_llm.complete.call_count == 3  # no decider
        # consensus scores still computed
        assert result.fields["total"].consensus is not None
        assert result.fields["total"].consensus.agreement == "3/3"

    async def test_disagreeing_candidates_still_run_decider(self):
        mock_llm = AsyncMock()
        # two candidates say 1234.56, one says 9999.99, decider resolves
        mock_llm.complete = AsyncMock(side_effect=[
            _make_llm_response(total=1234.56),
            _make_llm_response(total=9999.99),
            _make_llm_response(total=1234.56),
            _make_llm_response(total=1234.56),  # decider
        ])

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )

        assert mock_llm.complete.call_count == 4  # decider ran
        assert result.data["total"] == 1234.56
        assert result.fields["total"].consensus.agreement == "2/3"

    async def test_missing_field_in_one_candidate_runs_decider(self):
        import json as _json

        incomplete = LLMResponse(
            content=_json.dumps({
                "data": {"supplier_name": "Acme Corp"},  # total missing
                "evidence": {"supplier_name": {"page": 0, "text": "Acme Corp"}},
            }),
            model="gpt-4o",
        )
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=[
            _make_llm_response(),
            incomplete,
            _make_llm_response(),
            _make_llm_response(),  # decider
        ])

        engine = ExtractionEngine(llm=mock_llm)
        await engine.extract(
            _make_doc(), schema=Invoice, mode="multi", n_instances=3,
        )
        assert mock_llm.complete.call_count == 4


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
        # 3 candidate calls; identical responses are unanimous, so the
        # decider is skipped (consensus short-circuit)
        assert mock_llm.complete.call_count == 3

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

    async def test_multi_mode_repairs_schema_shaped_output(self):
        bad = {
            "data": {
                "tax_rate": "8.25%",
                "line_items": (
                    "1 Enterprise Data Platform License 1 $24,500.00 "
                    "8.25% $24,500.00"
                ),
            },
            "evidence": {
                "tax_rate": {"page": 0, "text": "8.25%"},
                "line_items": {
                    "page": 0,
                    "text": (
                        "1 Enterprise Data Platform License 1 $24,500.00 "
                        "8.25% $24,500.00"
                    ),
                },
            },
        }
        repaired = {
            "data": {
                "tax_rate": 8.25,
                "line_items": [
                    {
                        "description": "Enterprise Data Platform License",
                        "quantity": 1,
                        "unit_price": 24500.0,
                        "tax_rate": 8.25,
                        "amount": 24500.0,
                    }
                ],
            },
            "evidence": bad["evidence"],
        }

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=[
            LLMResponse(content=json.dumps(bad), model="gpt-4o"),
            LLMResponse(content=json.dumps(bad), model="gpt-4o"),
            LLMResponse(content=json.dumps(bad), model="gpt-4o"),
            LLMResponse(content=json.dumps(repaired), model="gpt-4o"),
        ])

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_doc(), schema=DetailedInvoice, mode="multi", n_instances=3,
        )

        assert mock_llm.complete.call_count == 4
        assert result.data["tax_rate"] == 8.25
        assert len(result.data["line_items"]) == 1
        assert result.data["line_items"][0]["amount"] == 24500.0

    async def test_multi_mode_all_fail_raises(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("all fail"))

        engine = ExtractionEngine(llm=mock_llm)
        from docuflow.errors import SchemaExtractionError

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
