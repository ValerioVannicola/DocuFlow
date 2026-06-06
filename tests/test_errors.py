from __future__ import annotations

import pytest

from docflow.errors import (
    DocflowError,
    EvidenceNotFoundError,
    HumanReviewRequired,
    OCRFailure,
    ParsingError,
    SchemaExtractionError,
    StorageError,
    UnsupportedFileTypeError,
    ValidationError,
    WorkflowError,
)

ALL_ERRORS = [
    UnsupportedFileTypeError,
    ParsingError,
    OCRFailure,
    SchemaExtractionError,
    EvidenceNotFoundError,
    StorageError,
    WorkflowError,
]


class TestErrorHierarchy:
    @pytest.mark.parametrize("error_cls", ALL_ERRORS)
    def test_is_subclass_of_docflow_error(self, error_cls):
        assert issubclass(error_cls, DocflowError)

    @pytest.mark.parametrize("error_cls", ALL_ERRORS)
    def test_can_raise_and_catch(self, error_cls):
        with pytest.raises(DocflowError):
            raise error_cls("test message")

    @pytest.mark.parametrize("error_cls", ALL_ERRORS)
    def test_message_preserved(self, error_cls):
        err = error_cls("something went wrong")
        assert str(err) == "something went wrong"


class TestValidationError:
    def test_is_docflow_error(self):
        assert issubclass(ValidationError, DocflowError)

    def test_with_field_and_rule(self):
        err = ValidationError("missing value", field_name="total", rule_name="required")
        assert err.field_name == "total"
        assert err.rule_name == "required"
        assert str(err) == "missing value"

    def test_without_optional_fields(self):
        err = ValidationError("bad data")
        assert err.field_name is None
        assert err.rule_name is None


class TestHumanReviewRequired:
    def test_is_docflow_error(self):
        assert issubclass(HumanReviewRequired, DocflowError)

    def test_with_details(self):
        err = HumanReviewRequired(
            "low confidence",
            document_id="doc-123",
            reason="confidence below threshold",
        )
        assert err.document_id == "doc-123"
        assert err.reason == "confidence below threshold"

    def test_without_optional_fields(self):
        err = HumanReviewRequired("needs review")
        assert err.document_id is None
        assert err.reason is None
