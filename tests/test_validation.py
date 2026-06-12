from __future__ import annotations

from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import ExtractedField, ExtractionResult
from docuflow.validation.base import ValidationError, Validator
from docuflow.validation.engine import validate
from docuflow.validation.validators import (
    CustomRule,
    EvidenceRequired,
    RequiredFields,
    TypeValidation,
)


def _make_result(**field_kwargs) -> ExtractionResult:
    fields = {}
    for name, val in field_kwargs.items():
        if isinstance(val, dict):
            fields[name] = ExtractedField(**val)
        else:
            fields[name] = ExtractedField(value=val, confidence=0.8)
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Test",
        data={k: v.value if isinstance(v, ExtractedField) else v for k, v in field_kwargs.items()},
        fields=fields,
    )


class TestRequiredFields:
    def test_passes_when_present(self):
        result = _make_result(name="Alice", age=30)
        errors = RequiredFields(["name", "age"]).validate(result)
        assert len(errors) == 0

    def test_catches_missing_field(self):
        result = _make_result(name="Alice")
        errors = RequiredFields(["name", "age"]).validate(result)
        assert len(errors) == 1
        assert errors[0].field_name == "age"

    def test_catches_none_value(self):
        result = _make_result(name="Alice", age={"value": None, "confidence": 0.5})
        errors = RequiredFields(["name", "age"]).validate(result)
        assert len(errors) == 1
        assert errors[0].field_name == "age"


class TestTypeValidation:
    def test_no_errors_for_valid(self):
        result = _make_result(name="Alice")
        errors = TypeValidation().validate(result)
        assert len(errors) == 0

    def test_warns_empty_string(self):
        result = _make_result(name={"value": "", "confidence": 0.5})
        errors = TypeValidation().validate(result)
        assert len(errors) == 1
        assert errors[0].severity == "warning"


class TestEvidenceRequired:
    def test_passes_with_evidence(self):
        ev = Evidence(document_id="doc-1", page_number=0, text="Alice")
        result = _make_result(name={"value": "Alice", "confidence": 0.9, "evidence": [ev.model_dump()]})
        # Reconstruct with proper evidence
        result.fields["name"].evidence = [ev]
        errors = EvidenceRequired().validate(result)
        assert len(errors) == 0

    def test_fails_without_evidence(self):
        result = _make_result(name="Alice")
        errors = EvidenceRequired().validate(result)
        assert len(errors) == 1
        assert errors[0].rule_name == "evidence_required"

    def test_specific_fields(self):
        result = _make_result(name="Alice", age=30)
        errors = EvidenceRequired(fields=["name"]).validate(result)
        assert len(errors) == 1
        assert errors[0].field_name == "name"


class TestCustomRule:
    def test_custom_rule(self):
        def check_total(result):
            total = result.fields.get("total")
            if total and total.value and total.value < 0:
                return [
                    ValidationError(
                        field_name="total",
                        rule_name="positive_total",
                        message="Total must be positive",
                    )
                ]
            return []

        result = _make_result(total=-100)
        errors = CustomRule("positive_total", check_total).validate(result)
        assert len(errors) == 1


class TestValidateEngine:
    def test_aggregates_errors(self):
        result = _make_result(name="Alice")
        validated = validate(result, [RequiredFields(["name", "age"]), EvidenceRequired()])
        assert len(validated.validation_errors) == 2  # missing age + no evidence for name

    def test_updates_field_status(self):
        result = _make_result(name="Alice", age=30)
        validated = validate(result, [RequiredFields(["name", "age"])])
        assert validated.fields["name"].validation_status == "valid"
        assert validated.fields["age"].validation_status == "valid"

    def test_error_status_on_failure(self):
        result = _make_result(name={"value": None, "confidence": 0.5})
        validated = validate(result, [RequiredFields(["name"])])
        assert validated.fields["name"].validation_status == "error"

    def test_protocol_compliance(self):
        assert isinstance(RequiredFields([]), Validator)
        assert isinstance(TypeValidation(), Validator)
        assert isinstance(EvidenceRequired(), Validator)
