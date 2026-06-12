from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from docflow.extraction.engine import ExtractionEngine
from docflow.extraction.llm.base import LLMResponse
from docflow.extraction.models import ReviewVerdict, TokenUsage


class Invoice(BaseModel):
    supplier_name: str
    total: float


def _make_document():
    from docflow.documents.models import Document, DocumentMetadata, Page

    return Document(
        id="doc-1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=[Page(page_number=0, text="Acme Corp\nTotal: 99.50")],
        raw_text="Acme Corp\nTotal: 99.50",
    )


def _llm_content() -> str:
    return json.dumps({
        "data": {"supplier_name": "Acme Corp", "total": 99.50},
        "evidence": {
            "supplier_name": {"page": 0, "text": "Acme Corp"},
            "total": {"page": 0, "text": "99.50"},
        },
    })


def _usage(prompt: int, completion: int, cost: float | None = None) -> dict:
    u = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
    if cost is not None:
        u["cost_usd"] = cost
    return u


class TestTokenUsageModel:
    def test_merged_sums_and_counts_calls(self):
        total = TokenUsage().merged(_usage(100, 20)).merged(_usage(50, 10))
        assert total.prompt_tokens == 150
        assert total.completion_tokens == 30
        assert total.total_tokens == 180
        assert total.n_llm_calls == 2
        assert total.cost_usd is None

    def test_merged_accumulates_cost_when_present(self):
        total = TokenUsage().merged(_usage(100, 20, cost=0.001)).merged(_usage(50, 10))
        assert total.cost_usd == pytest.approx(0.001)

    def test_combined_adds_aggregates(self):
        a = TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                       n_llm_calls=4, cost_usd=0.002)
        b = TokenUsage(prompt_tokens=50, completion_tokens=5, total_tokens=55,
                       n_llm_calls=1)
        c = a.combined(b)
        assert c.total_tokens == 175
        assert c.n_llm_calls == 5
        assert c.cost_usd == pytest.approx(0.002)

    def test_from_usages_empty_is_none(self):
        assert TokenUsage.from_usages([]) is None


class TestEngineUsageAggregation:
    async def test_single_mode_one_call(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content=_llm_content(), model="gpt-4o", usage=_usage(500, 100),
            )
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(_make_document(), schema=Invoice)

        assert result.usage is not None
        assert result.usage.n_llm_calls == 1
        assert result.usage.prompt_tokens == 500
        assert result.usage.total_tokens == 600

    async def test_multi_mode_sums_candidates_and_decider(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content=_llm_content(), model="gpt-4o", usage=_usage(500, 100),
            )
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(
            _make_document(), schema=Invoice, mode="multi", n_instances=3,
        )

        # 3 candidates; unanimous mock responses skip the decider
        assert result.usage is not None
        assert result.usage.n_llm_calls == 3
        assert result.usage.total_tokens == 600 * 3

    async def test_no_usage_reported_gives_none(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content=_llm_content(), model="gpt-4o")
        )
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(_make_document(), schema=Invoice)
        assert result.usage is None


class TestReviewerUsage:
    async def test_review_step_merges_reviewer_usage(self):
        from docflow.workflow.state import PipelineState
        from docflow.workflow.steps import Review

        class FakeReviewer:
            async def acheck(self, result, document_text=""):
                return ReviewVerdict(
                    reviewer="auditor", verdict="Approved",
                    usage=_usage(300, 50),
                )

        state = PipelineState()
        from docflow.extraction.models import ExtractionResult

        state.extraction_result = ExtractionResult(
            document_id="d1", schema_name="Invoice",
            usage=TokenUsage(prompt_tokens=500, completion_tokens=100,
                             total_tokens=600, n_llm_calls=1),
        )

        step = Review(rules=[FakeReviewer()])
        state = await step.execute(state)

        usage = state.extraction_result.usage
        assert usage.n_llm_calls == 2
        assert usage.total_tokens == 950

    async def test_review_step_creates_usage_when_absent(self):
        from docflow.workflow.state import PipelineState
        from docflow.workflow.steps import Review

        class FakeReviewer:
            async def acheck(self, result, document_text=""):
                return ReviewVerdict(
                    reviewer="auditor", verdict="Approved", usage=_usage(300, 50),
                )

        from docflow.extraction.models import ExtractionResult

        state = PipelineState()
        state.extraction_result = ExtractionResult(document_id="d1", schema_name="I")

        step = Review(rules=[FakeReviewer()])
        state = await step.execute(state)
        assert state.extraction_result.usage.total_tokens == 350
        assert state.extraction_result.usage.n_llm_calls == 1
