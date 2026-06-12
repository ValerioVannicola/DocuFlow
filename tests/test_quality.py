from __future__ import annotations

import json

from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import ExtractedField, ExtractionResult, FieldTrust
from docuflow.quality import FieldQuality, QualityReport, quality_report


def _field(
    value,
    confidence=0.9,
    found_in_source=True,
    auto_accept=True,
    agreement="5/5",
    agreement_ratio=1.0,
    evidence_text="some text",
    corrected=False,
):
    trust = FieldTrust(
        agreement=agreement,
        agreement_ratio=agreement_ratio,
        found_in_source=found_in_source,
        auto_accept=auto_accept,
        score=confidence,
    )
    evidence = (
        [Evidence(document_id="d", page_number=0, text=evidence_text)]
        if evidence_text
        else []
    )
    ef = ExtractedField(
        value=value, confidence=confidence, trust=trust, evidence=evidence,
    )
    if corrected:
        ef.original_value = "old"
        ef.corrected = True
    return ef


def _make_result(fields_dict, needs_review=False, review_reasons=None):
    data = {k: f.value for k, f in fields_dict.items()}
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Invoice",
        data=data,
        fields=fields_dict,
        confidence=0.9,
        needs_review=needs_review,
        review_reasons=review_reasons or [],
    )


class TestSingleResult:
    def test_perfect_result(self):
        fields = {
            "supplier": _field("Acme Corp"),
            "total": _field(1234.56),
        }
        report = quality_report(_make_result(fields))

        assert report.completeness_rate == 1.0
        assert report.grounding_rate == 1.0
        assert report.evidence_coverage == 1.0
        assert report.auto_accept_rate == 1.0
        assert report.mean_confidence == 0.9
        assert report.score == 0.98
        assert report.correction_rate == 0.0
        assert report.field_count == 2
        assert report.n_results == 1
        assert report.ok is True
        assert report.warnings == []
        assert report.worst_fields == []

    def test_no_evidence(self):
        fields = {
            "supplier": _field("Acme Corp", evidence_text=""),
        }
        report = quality_report(_make_result(fields))

        assert report.evidence_coverage == 0.0
        assert "no evidence" in report.warnings[0]
        assert report.field_details["supplier"].has_evidence is False

    def test_not_found_in_source(self):
        fields = {
            "supplier": _field("Acme Corp", found_in_source=False),
        }
        report = quality_report(_make_result(fields))

        assert report.grounding_rate == 0.0
        assert "not found in source" in report.warnings[0]
        assert report.field_details["supplier"].found_in_source is False

    def test_agent_disagreement(self):
        fields = {
            "total": _field(
                1234.56,
                auto_accept=False,
                agreement="3/5",
                agreement_ratio=0.6,
            ),
        }
        report = quality_report(_make_result(fields))

        assert report.auto_accept_rate == 0.0
        assert "disagreement" in report.warnings[0]
        assert report.field_details["total"].auto_accept is False

    def test_corrected_field(self):
        fields = {
            "total": _field(1235.00, corrected=True),
        }
        report = quality_report(_make_result(fields))

        assert report.correction_rate == 1.0
        assert report.field_details["total"].corrected is True
        assert any("human-corrected" in w for w in report.warnings)

    def test_mixed_quality(self):
        fields = {
            "supplier": _field("Acme Corp"),
            "total": _field(
                1234.56,
                confidence=0.6,
                found_in_source=False,
                auto_accept=False,
                agreement="2/5",
                agreement_ratio=0.4,
            ),
            "date": _field("2024-01-01", evidence_text=""),
        }
        report = quality_report(_make_result(fields))

        assert report.field_count == 3
        assert 0.0 < report.grounding_rate < 1.0
        assert 0.0 < report.evidence_coverage < 1.0
        assert 0.0 < report.auto_accept_rate < 1.0
        assert len(report.warnings) > 0
        assert "total" in report.worst_fields or "date" in report.worst_fields

    def test_empty_fields(self):
        result = ExtractionResult(
            document_id="doc-1",
            schema_name="Empty",
            data={},
            fields={},
        )
        report = quality_report(result)

        assert report.score == 0.0
        assert report.ok is False
        assert "No fields" in report.warnings[0]

    def test_needs_review_count(self):
        fields = {"total": _field(100)}
        result = _make_result(
            fields,
            needs_review=True,
            review_reasons=["Low confidence", "No evidence"],
        )
        report = quality_report(result)

        assert report.needs_review_count == 2

    def test_ok_threshold(self):
        fields = {
            "a": _field(1, confidence=0.3, found_in_source=False, auto_accept=False),
        }
        report = quality_report(_make_result(fields), threshold=0.5)
        assert report.ok is False

        report_low = quality_report(_make_result(fields), threshold=0.1)
        assert report_low.ok is True

    def test_score_range(self):
        fields = {"x": _field("val")}
        report = quality_report(_make_result(fields))
        assert 0.0 <= report.score <= 1.0

    def test_missing_field(self):
        fields = {
            "supplier": _field("Acme Corp"),
            "total": ExtractedField(value=None, confidence=0.0),
        }
        report = quality_report(_make_result(fields))

        assert report.completeness_rate == 0.5
        assert report.field_count == 2
        assert report.field_details["total"].missing is True
        assert report.field_details["supplier"].missing is False
        assert any("missing" in w for w in report.warnings)
        assert "total" in report.worst_fields

    def test_all_missing_fields(self):
        fields = {
            "a": ExtractedField(value=None),
            "b": ExtractedField(value=None),
        }
        report = quality_report(_make_result(fields))

        assert report.completeness_rate == 0.0
        assert report.grounding_rate == 0.0
        assert report.evidence_coverage == 0.0
        assert report.mean_confidence == 0.0
        assert report.score == 0.0
        assert report.ok is False
        assert len(report.warnings) == 2

    def test_completeness_in_score(self):
        all_present = {"a": _field("x"), "b": _field("y")}
        one_missing = {"a": _field("x"), "b": ExtractedField(value=None)}

        r_full = quality_report(_make_result(all_present))
        r_partial = quality_report(_make_result(one_missing))

        assert r_full.completeness_rate == 1.0
        assert r_partial.completeness_rate == 0.5
        assert r_full.score > r_partial.score


class TestBatchResults:
    def test_multiple_results(self):
        r1 = _make_result({"a": _field("x"), "b": _field("y")})
        r2 = _make_result({"a": _field("x"), "b": _field("y")})
        r3 = _make_result({"a": _field("x"), "b": _field("y")})

        report = quality_report([r1, r2, r3])

        assert report.n_results == 3
        assert report.score == 0.98
        assert report.field_count == 6
        assert report.ok is True

    def test_empty_list(self):
        report = quality_report([])

        assert report.n_results == 0
        assert report.ok is False
        assert "No results" in report.warnings[0]

    def test_batch_averages(self):
        r_good = _make_result({"a": _field("x")})
        r_bad = _make_result({
            "a": _field("x", confidence=0.2, found_in_source=False, auto_accept=False, evidence_text=""),
        })

        report = quality_report([r_good, r_bad])

        assert report.n_results == 2
        assert 0.0 < report.score < 1.0
        assert 0.0 < report.grounding_rate < 1.0

    def test_worst_fields_across_batch(self):
        r1 = _make_result({
            "good": _field("x"),
            "bad": _field("y", confidence=0.1, found_in_source=False, auto_accept=False, evidence_text=""),
        })
        r2 = _make_result({
            "good": _field("x"),
            "bad": _field("y", confidence=0.1, found_in_source=False, auto_accept=False, evidence_text=""),
        })

        report = quality_report([r1, r2])

        assert "bad" in report.worst_fields

    def test_batch_correction_rate(self):
        r1 = _make_result({"a": _field("x", corrected=True)})
        r2 = _make_result({"a": _field("x", corrected=False)})

        report = quality_report([r1, r2])

        assert report.correction_rate == 0.5

    def test_batch_warnings_prefixed(self):
        r1 = _make_result({"a": _field("x", evidence_text="")})
        r2 = _make_result({"a": _field("x")})

        report = quality_report([r1, r2])

        assert any("[result 0]" in w for w in report.warnings)

    def test_batch_no_field_details(self):
        r1 = _make_result({"a": _field("x")})
        report = quality_report([r1])
        assert report.field_details == {}

    def test_batch_completeness_rate(self):
        r_full = _make_result({"a": _field("x"), "b": _field("y")})
        r_partial = _make_result({
            "a": _field("x"),
            "b": ExtractedField(value=None),
        })

        report = quality_report([r_full, r_partial])

        assert report.completeness_rate == 0.75


class TestSerialization:
    def test_json_roundtrip(self):
        fields = {"total": _field(100.0, corrected=True)}
        report = quality_report(_make_result(fields))

        data = json.loads(report.model_dump_json())
        restored = QualityReport.model_validate(data)

        assert restored.score == report.score
        assert restored.field_count == report.field_count
        assert restored.correction_rate == report.correction_rate

    def test_field_quality_model(self):
        fq = FieldQuality(
            confidence=0.9,
            found_in_source=True,
            has_evidence=True,
            auto_accept=True,
            corrected=False,
            warning="",
        )
        data = json.loads(fq.model_dump_json())
        assert data["confidence"] == 0.9
        assert data["corrected"] is False
