from __future__ import annotations

from collections.abc import Callable

from docuflow.extraction.models import ExtractionResult
from docuflow.validation.base import ValidationError


class RequiredFields:
    def __init__(self, fields: list[str]):
        self.fields = fields

    def validate(self, result: ExtractionResult) -> list[ValidationError]:
        errors: list[ValidationError] = []
        for field_name in self.fields:
            if field_name not in result.fields:
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        rule_name="required_fields",
                        message=f"Required field '{field_name}' is missing",
                    )
                )
            elif result.fields[field_name].value is None:
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        rule_name="required_fields",
                        message=f"Required field '{field_name}' has no value",
                    )
                )
        return errors


class TypeValidation:
    def validate(self, result: ExtractionResult) -> list[ValidationError]:
        errors: list[ValidationError] = []
        for field_name, field in result.fields.items():
            if field.value is not None and isinstance(field.value, str) and field.value == "":
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        rule_name="type_validation",
                        message=f"Field '{field_name}' has empty string value",
                        severity="warning",
                    )
                )
        return errors


class EvidenceRequired:
    def __init__(self, fields: list[str] | None = None):
        self.fields = fields

    def validate(self, result: ExtractionResult) -> list[ValidationError]:
        errors: list[ValidationError] = []
        check_fields = self.fields or list(result.fields.keys())
        for field_name in check_fields:
            if field_name in result.fields:
                field = result.fields[field_name]
                if field.value is not None and not field.evidence:
                    errors.append(
                        ValidationError(
                            field_name=field_name,
                            rule_name="evidence_required",
                            message=f"Field '{field_name}' has no supporting evidence",
                        )
                    )
        return errors


class CustomRule:
    def __init__(
        self,
        name: str,
        fn: Callable[[ExtractionResult], list[ValidationError]],
    ):
        self.name = name
        self.fn = fn

    def validate(self, result: ExtractionResult) -> list[ValidationError]:
        return self.fn(result)
