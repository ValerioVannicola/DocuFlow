from __future__ import annotations

from docflow.extraction.models import ExtractionResult
from docflow.validation.base import ValidationError, Validator


def validate(
    result: ExtractionResult,
    validators: list[Validator],
) -> ExtractionResult:
    """Run all validators and update the result with errors and field statuses."""
    all_errors: list[ValidationError] = []

    for validator in validators:
        errors = validator.validate(result)
        all_errors.extend(errors)

    result.validation_errors = [e.model_dump() for e in all_errors]

    error_fields: dict[str, str] = {}
    for error in all_errors:
        current = error_fields.get(error.field_name, "valid")
        if error.severity == "error":
            error_fields[error.field_name] = "error"
        elif error.severity == "warning" and current != "error":
            error_fields[error.field_name] = "warning"

    for field_name, field in result.fields.items():
        status = error_fields.get(field_name, "valid")
        field.validation_status = status
        field.errors = [
            e.message for e in all_errors if e.field_name == field_name
        ]

    return result
