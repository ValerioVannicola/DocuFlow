from __future__ import annotations

import json

from docuflow.eval import EvalHarness, _fuzzy_match, _normalize
from docuflow.extraction.models import ExtractedField, ExtractionResult, FieldTrust


def _make_result(
    doc_id: str,
    fields: dict[str, tuple],
    corrected_fields: dict[str, tuple] | None = None,
) -> ExtractionResult:
    extracted = {}
    data = {}
    for fname, (value, found) in fields.items():
        trust = FieldTrust(found_in_source=found, agreement="1/1", trust_gate=found)
        ef = ExtractedField(value=value, trust=trust)
        extracted[fname] = ef
        data[fname] = value

    if corrected_fields:
        for fname, (original, corrected) in corrected_fields.items():
            if fname in extracted:
                extracted[fname].value = corrected
                extracted[fname].original_value = original
                extracted[fname].corrected = True
                data[fname] = corrected

    return ExtractionResult(
        document_id=doc_id,
        schema_name="Test",
        data=data,
        fields=extracted,
    )


class TestNormalize:
    def test_strips_currency(self):
        assert _normalize("$1,234.56") == "1234.56"
        assert _normalize("€100") == "100"

    def test_lowercase(self):
        assert _normalize("Acme Corp") == "acme corp"

    def test_whitespace(self):
        assert _normalize("  hello   world  ") == "hello world"


class TestFuzzyMatch:
    def test_exact(self):
        assert _fuzzy_match("Acme Corp", "Acme Corp")

    def test_case_insensitive(self):
        assert _fuzzy_match("acme corp", "Acme Corp")

    def test_substring(self):
        assert _fuzzy_match("Acme", "Acme Corp Inc")

    def test_no_match(self):
        assert not _fuzzy_match("Alpha", "Beta")

    def test_empty(self):
        assert not _fuzzy_match("", "something")


class TestEvalHarness:
    def test_perfect_accuracy(self):
        gt = _make_result("d1", {"name": ("Acme", True), "total": (100.0, True)})
        pred = _make_result("d1", {"name": ("Acme", True), "total": (100.0, True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.overall_accuracy == 1.0
        assert report.field_accuracy["name"] == 1.0
        assert report.field_accuracy["total"] == 1.0

    def test_wrong_value(self):
        gt = _make_result("d1", {"name": ("Acme", True), "total": (100.0, True)})
        pred = _make_result("d1", {"name": ("Acme", True), "total": (999.0, True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.field_accuracy["name"] == 1.0
        assert report.field_accuracy["total"] == 0.0
        assert report.field_scores["total"].wrong == 1

    def test_missing_field(self):
        gt = _make_result("d1", {"name": ("Acme", True), "total": (100.0, True)})
        pred = _make_result("d1", {"name": ("Acme", True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.field_scores["total"].missing == 1

    def test_hallucination_detected(self):
        gt = _make_result("d1", {"name": ("Acme", True)})
        pred = _make_result("d1", {"name": ("Fake Corp", False)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.field_scores["name"].hallucinated == 1
        assert report.hallucination_rate > 0

    def test_fuzzy_match_counts(self):
        gt = _make_result("d1", {"name": ("Acme Corporation", True)})
        pred = _make_result("d1", {"name": ("Acme Corp", True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.field_scores["name"].fuzzy_match == 1
        assert report.field_accuracy["name"] == 1.0

    def test_multiple_documents(self):
        gt1 = _make_result("d1", {"total": (100.0, True)})
        gt2 = _make_result("d2", {"total": (200.0, True)})
        gt3 = _make_result("d3", {"total": (300.0, True)})

        pred1 = _make_result("d1", {"total": (100.0, True)})
        pred2 = _make_result("d2", {"total": (200.0, True)})
        pred3 = _make_result("d3", {"total": (999.0, True)})

        harness = EvalHarness()
        for gt in [gt1, gt2, gt3]:
            harness.add_ground_truth(gt)

        report = harness.compare_results(predicted=[pred1, pred2, pred3])

        assert report.total_documents == 3
        assert report.field_scores["total"].exact_match == 2
        assert report.field_scores["total"].wrong == 1

    def test_correction_rate(self):
        gt = _make_result(
            "d1", {"total": (100.0, True)},
            corrected_fields={"total": (99.0, 100.0)},
        )
        pred = _make_result("d1", {"total": (100.0, True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        assert report.overall_accuracy == 1.0

    def test_ground_truth_from_dict(self):
        harness = EvalHarness()
        harness.add_ground_truth_dict("d1", {"name": "Acme", "total": 100.0})

        pred = _make_result("d1", {"name": ("Acme", True), "total": (100.0, True)})
        report = harness.compare_results(predicted=[pred])

        assert report.overall_accuracy == 1.0

    def test_missing_prediction(self):
        gt = _make_result("d1", {"name": ("Acme", True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[])

        assert report.field_scores["name"].missing == 1

    def test_report_serializes(self):
        gt = _make_result("d1", {"name": ("Acme", True)})
        pred = _make_result("d1", {"name": ("Acme", True)})

        harness = EvalHarness()
        harness.add_ground_truth(gt)
        report = harness.compare_results(predicted=[pred])

        output = json.loads(report.model_dump_json())
        assert "field_accuracy" in output
        assert "overall_accuracy" in output
        assert "hallucination_rate" in output

    def test_ground_truth_count(self):
        harness = EvalHarness()
        assert harness.ground_truth_count == 0

        harness.add_ground_truth_dict("d1", {"name": "Acme"})
        harness.add_ground_truth_dict("d2", {"name": "Beta"})
        assert harness.ground_truth_count == 2
