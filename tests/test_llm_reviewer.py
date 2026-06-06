from __future__ import annotations

import json
from unittest.mock import AsyncMock

from docflow.documents.evidence import Evidence
from docflow.documents.models import Document, DocumentMetadata, Page
from docflow.extraction.llm.base import LLMResponse
from docflow.extraction.models import ExtractedField, ExtractionResult, ReviewVerdict
from docflow.review.llm_reviewer import LLMReviewer
from docflow.review.rules import OverallConfidenceBelow
from docflow.workflow.state import PipelineState
from docflow.workflow.steps import Review


def _make_result() -> ExtractionResult:
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Invoice",
        data={"supplier_name": "Acme Corp", "total": 1234.56},
        fields={
            "supplier_name": ExtractedField(
                value="Acme Corp", confidence=0.9,
                evidence=[Evidence(document_id="d", page_number=0, text="Acme Corp")],
            ),
            "total": ExtractedField(
                value=1234.56, confidence=0.8,
                evidence=[Evidence(document_id="d", page_number=0, text="1234.56")],
            ),
        },
        confidence=0.85,
    )


def _make_state() -> PipelineState:
    state = PipelineState()
    state.extraction_result = _make_result()
    state.document = Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf",
        ),
        pages=[Page(page_number=0, text="Invoice from Acme Corp. Total: 1234.56")],
        raw_text="Invoice from Acme Corp. Total: 1234.56",
    )
    return state


class TestLLMReviewer:
    async def test_approved(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": "All looks good"}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        verdict = await reviewer.acheck(_make_result(), document_text="some text")

        assert isinstance(verdict, ReviewVerdict)
        assert verdict.verdict == "Approved"
        assert verdict.reviewer == "auditor"
        assert verdict.reasoning == "All looks good"

    async def test_not_approved(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "verdict": "Not Approved",
                "reasoning": "Total does not match line items",
            }),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        verdict = await reviewer.acheck(_make_result(), document_text="some text")

        assert isinstance(verdict, ReviewVerdict)
        assert verdict.verdict == "Not Approved"
        assert "Total does not match" in verdict.reasoning

    async def test_llm_failure_returns_not_approved(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("API down"))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        verdict = await reviewer.acheck(_make_result())

        assert verdict.verdict == "Not Approved"
        assert "failed" in verdict.reasoning

    async def test_bad_json_returns_not_approved(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="not json at all", model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        verdict = await reviewer.acheck(_make_result())

        assert verdict.verdict == "Not Approved"
        assert "failed" in verdict.reasoning

    async def test_normalizes_verdict_string(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "approved", "reasoning": "ok"}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="test", prompt="test", llm=mock_llm)
        verdict = await reviewer.acheck(_make_result())
        assert verdict.verdict == "Approved"

    async def test_prompt_includes_data_and_evidence(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": ""}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="test", prompt="Custom instruction.", llm=mock_llm)
        await reviewer.acheck(_make_result(), document_text="doc text")

        call_messages = mock_llm.complete.call_args[0][0]
        user_msg = call_messages[1]["content"]
        assert "Custom instruction." in user_msg
        assert "Acme Corp" in user_msg
        assert "1234.56" in user_msg
        assert "doc text" in user_msg

    def test_sync_check_returns_none(self):
        mock_llm = AsyncMock()
        reviewer = LLMReviewer(name="test", prompt="test", llm=mock_llm)
        assert reviewer.check(_make_result()) is None


class TestReviewStepWithVerdicts:
    async def test_verdict_stored_on_result(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "verdict": "Not Approved",
                "reasoning": "Totals mismatch",
            }),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        step = Review(rules=[reviewer])
        state = _make_state()
        result = await step.execute(state)

        assert result.extraction_result.needs_review is True
        assert len(result.extraction_result.review_verdicts) == 1
        v = result.extraction_result.review_verdicts[0]
        assert v.verdict == "Not Approved"
        assert v.reviewer == "auditor"
        assert "Totals mismatch" in v.reasoning

    async def test_approved_verdict_stored_no_review_needed(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": "All good"}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check totals.", llm=mock_llm)
        step = Review(rules=[reviewer])
        state = _make_state()
        result = await step.execute(state)

        assert not result.extraction_result.needs_review
        assert len(result.extraction_result.review_verdicts) == 1
        assert result.extraction_result.review_verdicts[0].verdict == "Approved"

    async def test_multiple_reviewers_all_stored(self):
        llm1 = AsyncMock()
        llm1.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": "Math ok"}),
            model="gpt-4o",
        ))
        llm2 = AsyncMock()
        llm2.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Not Approved", "reasoning": "PII found"}),
            model="gpt-4o",
        ))

        auditor = LLMReviewer(name="auditor", prompt="Check math.", llm=llm1)
        compliance = LLMReviewer(name="compliance", prompt="Check PII.", llm=llm2)

        step = Review(rules=[auditor, compliance])
        state = _make_state()
        result = await step.execute(state)

        assert result.extraction_result.needs_review is True
        assert len(result.extraction_result.review_verdicts) == 2
        verdicts = {v.reviewer: v.verdict for v in result.extraction_result.review_verdicts}
        assert verdicts["auditor"] == "Approved"
        assert verdicts["compliance"] == "Not Approved"

    async def test_mix_rules_and_reviewers_with_verdicts(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": ""}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check.", llm=mock_llm)
        step = Review(rules=[OverallConfidenceBelow(0.9), reviewer])
        state = _make_state()
        result = await step.execute(state)

        # Rule flags (0.85 < 0.9), reviewer approves
        assert result.extraction_result.needs_review is True
        assert len(result.extraction_result.review_verdicts) == 1
        assert result.extraction_result.review_verdicts[0].verdict == "Approved"
        assert len(result.extraction_result.review_reasons) == 1

    async def test_verdicts_in_json_output(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"verdict": "Approved", "reasoning": "All good"}),
            model="gpt-4o",
        ))

        reviewer = LLMReviewer(name="auditor", prompt="Check.", llm=mock_llm)
        step = Review(rules=[reviewer])
        state = _make_state()
        result = await step.execute(state)

        json_output = json.loads(result.extraction_result.model_dump_json())
        assert "review_verdicts" in json_output
        assert json_output["review_verdicts"][0]["verdict"] == "Approved"
        assert json_output["review_verdicts"][0]["reviewer"] == "auditor"
