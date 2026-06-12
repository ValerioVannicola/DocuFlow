from __future__ import annotations

from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import ExtractedField, ExtractionResult
from docuflow.review.rules import (
    AnyFieldConfidenceBelow,
    FieldConfidenceBelow,
    FieldMissing,
    HasValidationErrors,
    NoEvidence,
    OverallConfidenceBelow,
    ReviewRule,
)
from docuflow.workflow.state import PipelineState
from docuflow.workflow.steps import PipelineStep, Review


def _make_result(
    confidence: float = 0.8,
    fields: dict | None = None,
    validation_errors: list | None = None,
) -> ExtractionResult:
    if fields is None:
        fields = {
            "supplier_name": ExtractedField(
                value="Acme Corp", confidence=0.9,
                evidence=[Evidence(document_id="d", page_number=0, text="Acme Corp")],
            ),
            "total": ExtractedField(
                value=1234.56, confidence=0.7,
                evidence=[Evidence(document_id="d", page_number=0, text="1234.56")],
            ),
        }
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Invoice",
        data={k: f.value for k, f in fields.items()},
        fields=fields,
        confidence=confidence,
        validation_errors=validation_errors or [],
    )


class TestOverallConfidenceBelow:
    def test_passes_when_above(self):
        result = _make_result(confidence=0.8)
        assert OverallConfidenceBelow(0.7).check(result) is None

    def test_flags_when_below(self):
        result = _make_result(confidence=0.5)
        reason = OverallConfidenceBelow(0.7).check(result)
        assert reason is not None
        assert "0.50" in reason
        assert "0.7" in reason

    def test_default_threshold(self):
        assert OverallConfidenceBelow().threshold == 0.7


class TestFieldConfidenceBelow:
    def test_passes_when_all_above(self):
        result = _make_result()
        rule = FieldConfidenceBelow({"supplier_name": 0.8, "total": 0.6})
        assert rule.check(result) is None

    def test_flags_specific_field(self):
        result = _make_result()
        rule = FieldConfidenceBelow({"total": 0.8})
        reason = rule.check(result)
        assert reason is not None
        assert "total" in reason

    def test_ignores_missing_field(self):
        result = _make_result()
        rule = FieldConfidenceBelow({"nonexistent": 0.9})
        assert rule.check(result) is None


class TestAnyFieldConfidenceBelow:
    def test_passes_when_all_above(self):
        result = _make_result()
        assert AnyFieldConfidenceBelow(0.5).check(result) is None

    def test_flags_lowest_field(self):
        result = _make_result()
        reason = AnyFieldConfidenceBelow(0.8).check(result)
        assert reason is not None
        assert "total" in reason


class TestHasValidationErrors:
    def test_passes_with_no_errors(self):
        result = _make_result(validation_errors=[])
        assert HasValidationErrors().check(result) is None

    def test_flags_with_errors(self):
        result = _make_result(
            validation_errors=[{"field_name": "total", "message": "missing"}]
        )
        reason = HasValidationErrors().check(result)
        assert reason is not None
        assert "1 validation error" in reason


class TestFieldMissing:
    def test_passes_when_present(self):
        result = _make_result()
        assert FieldMissing(["supplier_name", "total"]).check(result) is None

    def test_flags_missing_field(self):
        result = _make_result()
        reason = FieldMissing(["supplier_name", "invoice_number"]).check(result)
        assert reason is not None
        assert "invoice_number" in reason

    def test_flags_none_value(self):
        fields = {
            "total": ExtractedField(value=None, confidence=0.0),
        }
        result = _make_result(fields=fields)
        reason = FieldMissing(["total"]).check(result)
        assert reason is not None
        assert "total" in reason


class TestNoEvidence:
    def test_passes_with_evidence(self):
        result = _make_result()
        assert NoEvidence().check(result) is None

    def test_flags_no_evidence(self):
        fields = {
            "total": ExtractedField(value=1234.56, confidence=0.7, evidence=[]),
        }
        result = _make_result(fields=fields)
        reason = NoEvidence().check(result)
        assert reason is not None
        assert "total" in reason

    def test_checks_specific_fields(self):
        fields = {
            "name": ExtractedField(value="Acme", confidence=0.9, evidence=[]),
            "total": ExtractedField(
                value=100, confidence=0.8,
                evidence=[Evidence(document_id="d", page_number=0, text="100")],
            ),
        }
        result = _make_result(fields=fields)
        assert NoEvidence(fields=["total"]).check(result) is None
        assert NoEvidence(fields=["name"]).check(result) is not None


class TestReviewStep:
    def test_protocol_compliance(self):
        assert isinstance(Review(), PipelineStep)

    async def test_no_rules_no_review(self):
        state = PipelineState()
        state.extraction_result = _make_result()
        step = Review(rules=[])
        result = await step.execute(state)
        assert not result.extraction_result.needs_review
        assert result.extraction_result.review_reasons == []

    async def test_rule_triggers_review(self):
        state = PipelineState()
        state.extraction_result = _make_result(confidence=0.3)
        step = Review(rules=[OverallConfidenceBelow(0.5)])
        result = await step.execute(state)
        assert result.extraction_result.needs_review is True
        assert len(result.extraction_result.review_reasons) == 1

    async def test_multiple_rules(self):
        fields = {
            "total": ExtractedField(value=None, confidence=0.2, evidence=[]),
        }
        state = PipelineState()
        state.extraction_result = _make_result(confidence=0.2, fields=fields)
        step = Review(rules=[
            OverallConfidenceBelow(0.5),
            FieldMissing(["total"]),
            NoEvidence(),
        ])
        result = await step.execute(state)
        assert result.extraction_result.needs_review is True
        assert len(result.extraction_result.review_reasons) >= 2

    async def test_all_pass_no_review(self):
        state = PipelineState()
        state.extraction_result = _make_result(confidence=0.9)
        step = Review(rules=[
            OverallConfidenceBelow(0.5),
            HasValidationErrors(),
        ])
        result = await step.execute(state)
        assert not result.extraction_result.needs_review

    async def test_errors_without_result(self):
        state = PipelineState()
        step = Review(rules=[OverallConfidenceBelow(0.5)])
        result = await step.execute(state)
        assert result.status == "failed"

    def test_rule_protocol_compliance(self):
        assert isinstance(OverallConfidenceBelow(), ReviewRule)
        assert isinstance(FieldConfidenceBelow({}), ReviewRule)
        assert isinstance(AnyFieldConfidenceBelow(), ReviewRule)
        assert isinstance(HasValidationErrors(), ReviewRule)
        assert isinstance(FieldMissing([]), ReviewRule)
        assert isinstance(NoEvidence(), ReviewRule)


class TestDocumentPipelineReview:
    def test_pipeline_accepts_review_rules(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            review_rules=[OverallConfidenceBelow(0.7), FieldMissing(["total"])],
        )
        assert len(pipeline._review_rules) == 2

    def test_pipeline_no_review_by_default(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline()
        assert pipeline._review_rules == []
