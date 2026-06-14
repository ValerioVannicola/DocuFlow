from __future__ import annotations

import json

from docuflow.documents.evidence import Evidence
from docuflow.documents.models import BoundingBox
from docuflow.extraction.models import (
    ExtractedField,
    ExtractionResult,
    FieldProvenance,
    FieldTrust,
    ReviewVerdict,
)


def _make_result() -> ExtractionResult:
    bbox = BoundingBox(x0=72, y0=130, x1=300, y1=148)
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Invoice",
        data={"supplier_name": "Acme Corp", "total": 1234.56},
        fields={
            "supplier_name": ExtractedField(
                value="Acme Corp", trust=FieldTrust(found_in_source=True, trust_gate=True),
                evidence=[Evidence(
                    document_id="doc-1", page_number=0,
                    text="Acme Corp", bbox=bbox, block_id="b1",
                    confidence=0.95,
                )],
                validation_status="valid",
            ),
            "total": ExtractedField(
                value=1234.56, trust=FieldTrust(found_in_source=True, trust_gate=True),
                evidence=[Evidence(
                    document_id="doc-1", page_number=1,
                    text="1234.56", confidence=0.85,
                )],
                validation_status="valid",
            ),
        },
        confidence=0.8,
        model_name="gpt-4o",
        parser_name="tesseract",
    )


class TestProvenance:
    def test_basic_provenance(self):
        result = _make_result()
        prov = result.provenance()

        assert "supplier_name" in prov
        assert "total" in prov
        assert isinstance(prov["supplier_name"], FieldProvenance)

    def test_field_values(self):
        result = _make_result()
        prov = result.provenance()

        p = prov["supplier_name"]
        assert p.value == "Acme Corp"
        assert p.trust_gate is True
        assert p.source_text == "Acme Corp"
        assert p.page == 0
        assert p.bbox is not None
        assert p.block_id == "b1"
        assert p.evidence_confidence == 0.95
        assert p.model_name == "gpt-4o"
        assert p.parser_name == "tesseract"
        assert p.validation_status == "valid"

    def test_single_field(self):
        result = _make_result()
        prov = result.provenance("total")

        assert len(prov) == 1
        assert "total" in prov
        assert prov["total"].page == 1

    def test_nonexistent_field(self):
        result = _make_result()
        prov = result.provenance("nonexistent")
        assert len(prov) == 0

    def test_with_correction(self):
        result = _make_result()
        result.correct_field("total", 1235.00, corrected_by="john", reason="OCR error")

        prov = result.provenance("total")
        p = prov["total"]
        assert p.corrected is True
        assert p.value == 1235.00
        assert p.original_value == 1234.56
        assert p.corrected_by == "john"
        assert p.correction_reason == "OCR error"

    def test_with_review(self):
        result = _make_result()
        result.review_verdicts = [
            ReviewVerdict(reviewer="auditor", verdict="Approved", reasoning="OK"),
        ]
        result.approve(approved_by="john")

        prov = result.provenance()
        p = prov["supplier_name"]
        assert p.reviewed is True
        assert p.review_status == "approved"
        assert p.reviewed_by == "john"
        assert len(p.review_verdicts) > 0

    def test_no_evidence(self):
        result = ExtractionResult(
            document_id="doc-1",
            schema_name="Test",
            data={"name": "value"},
            fields={"name": ExtractedField(value="value", trust=FieldTrust(found_in_source=True, trust_gate=True))},
        )
        prov = result.provenance()
        p = prov["name"]
        assert p.source_text == ""
        assert p.page is None
        assert p.bbox is None

    def test_serializes_to_json(self):
        result = _make_result()
        prov = result.provenance()

        for _fname, p in prov.items():
            output = json.loads(p.model_dump_json())
            assert "field_name" in output
            assert "value" in output
            assert "source_text" in output
            assert "model_name" in output

    def test_full_lifecycle(self):
        result = _make_result()
        result.review_verdicts = [
            ReviewVerdict(reviewer="auditor", verdict="Not Approved", reasoning="Total wrong"),
        ]
        result.correct_field("total", 1235.00, corrected_by="john", reason="Fix")
        result.approve(approved_by="john")

        prov = result.provenance("total")
        p = prov["total"]

        assert p.value == 1235.00
        assert p.original_value == 1234.56
        assert p.corrected is True
        assert p.corrected_by == "john"
        assert p.source_text == "1234.56"
        assert p.page == 1
        assert p.model_name == "gpt-4o"
        assert p.review_status == "approved"
        assert p.reviewed_by == "john"
