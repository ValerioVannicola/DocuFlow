from __future__ import annotations

import json

import pytest

from docflow.documents.evidence import Evidence
from docflow.extraction.models import (
    ExtractedField,
    ExtractionResult,
)


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


class TestCorrectField:
    def test_basic_correction(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john", reason="OCR misread")

        assert result.fields["total"].value == 1235.00
        assert result.fields["total"].original_value == 1234.56
        assert result.fields["total"].corrected is True
        assert result.data["total"] == 1235.00

    def test_original_value_preserved_on_second_correction(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john", reason="first fix")
        result.correct_field("total", 1236.00, corrected_by="jane", reason="second fix")

        assert result.fields["total"].value == 1236.00
        assert result.fields["total"].original_value == 1234.56
        assert len(result.corrections) == 2

    def test_correction_audit_trail(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john", reason="OCR error")

        assert len(result.corrections) == 1
        c = result.corrections[0]
        assert c.field_name == "total"
        assert c.old_value == 1234.56
        assert c.new_value == 1235.00
        assert c.corrected_by == "john"
        assert c.reason == "OCR error"
        assert c.timestamp is not None

    def test_multiple_field_corrections(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john")
        result.correct_field("supplier_name", "Acme Inc", corrected_by="jane")

        assert result.fields["total"].corrected is True
        assert result.fields["supplier_name"].corrected is True
        assert result.data["total"] == 1235.00
        assert result.data["supplier_name"] == "Acme Inc"
        assert len(result.corrections) == 2

    def test_correction_nonexistent_field_raises(self):
        result = _make_result()
        with pytest.raises(KeyError, match="nonexistent"):
            result.correct_field("nonexistent", "value")

    def test_uncorrected_field_has_no_original(self):
        result = _make_result()
        assert result.fields["total"].original_value is None
        assert result.fields["total"].corrected is False

    def test_correction_to_none(self):
        result = _make_result()
        result.correct_field("total", None, corrected_by="john", reason="field not in doc")

        assert result.fields["total"].value is None
        assert result.fields["total"].original_value == 1234.56
        assert result.data["total"] is None

    def test_corrections_serialize_to_json(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john", reason="fix")

        output = json.loads(result.model_dump_json())
        assert len(output["corrections"]) == 1
        assert output["corrections"][0]["field_name"] == "total"
        assert output["corrections"][0]["old_value"] == 1234.56
        assert output["corrections"][0]["new_value"] == 1235.00
        assert output["fields"]["total"]["corrected"] is True
        assert output["fields"]["total"]["original_value"] == 1234.56


class TestApproveReject:
    def test_approve(self):
        result = _make_result()
        result.needs_review = True
        result.approve(approved_by="john")

        assert result.review_status == "approved"
        assert result.reviewed_by == "john"
        assert result.reviewed_at is not None

    def test_reject(self):
        result = _make_result()
        result.needs_review = True
        result.reject(rejected_by="john", reason="wrong document type")

        assert result.review_status == "rejected"
        assert result.reviewed_by == "john"
        assert result.reviewed_at is not None
        assert result.rejection_reason == "wrong document type"

    def test_cannot_approve_twice(self):
        result = _make_result()
        result.approve(approved_by="john")
        with pytest.raises(ValueError, match="already 'approved'"):
            result.approve(approved_by="jane")

    def test_cannot_reject_twice(self):
        result = _make_result()
        result.reject(rejected_by="john", reason="bad")
        with pytest.raises(ValueError, match="already 'rejected'"):
            result.reject(rejected_by="jane", reason="also bad")

    def test_cannot_approve_after_reject(self):
        result = _make_result()
        result.reject(rejected_by="john", reason="bad")
        with pytest.raises(ValueError, match="already 'rejected'"):
            result.approve(approved_by="jane")

    def test_cannot_reject_after_approve(self):
        result = _make_result()
        result.approve(approved_by="john")
        with pytest.raises(ValueError, match="already 'approved'"):
            result.reject(rejected_by="jane", reason="changed mind")

    def test_default_review_status_is_pending(self):
        result = _make_result()
        assert result.review_status == "pending"
        assert result.reviewed_by == ""
        assert result.reviewed_at is None
        assert result.rejection_reason == ""

    def test_approve_without_name(self):
        result = _make_result()
        result.approve()
        assert result.review_status == "approved"
        assert result.reviewed_by == ""

    def test_approval_serializes_to_json(self):
        result = _make_result()
        result.approve(approved_by="john")

        output = json.loads(result.model_dump_json())
        assert output["review_status"] == "approved"
        assert output["reviewed_by"] == "john"
        assert output["reviewed_at"] is not None


class TestCorrectThenApprove:
    def test_full_workflow(self):
        result = _make_result()
        result.needs_review = True

        result.correct_field("total", 1235.00, corrected_by="john", reason="OCR error")
        result.approve(approved_by="john")

        assert result.review_status == "approved"
        assert result.fields["total"].value == 1235.00
        assert result.fields["total"].original_value == 1234.56
        assert len(result.corrections) == 1

        output = json.loads(result.model_dump_json())
        assert output["review_status"] == "approved"
        assert output["corrections"][0]["corrected_by"] == "john"
        assert output["data"]["total"] == 1235.00
