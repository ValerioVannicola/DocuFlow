from __future__ import annotations

import pydantic
import pytest

from docflow.errors import AnonymizationError, DocflowError, PrivacyError
from docflow.privacy.models import (
    AnonymizationMode,
    AnonymizationResult,
    AnonymizedText,
    PrivacyFinding,
    TokenMapping,
)
from docflow.privacy.policy import PrivacyPolicy


class TestAnonymizationMode:
    def test_values(self):
        assert AnonymizationMode.REDACT == "redact"
        assert AnonymizationMode.MASK == "mask"
        assert AnonymizationMode.PSEUDONYMIZE == "pseudonymize"
        assert AnonymizationMode.HASH == "hash"


class TestPrivacyFinding:
    def test_create(self):
        f = PrivacyFinding(entity_type="PERSON", start=0, end=10, text="John Doe", score=0.95)
        assert f.entity_type == "PERSON"
        assert f.text == "John Doe"
        assert f.page_number is None

    def test_frozen(self):
        f = PrivacyFinding(entity_type="PERSON", start=0, end=5, text="John", score=0.9)
        with pytest.raises(pydantic.ValidationError):
            f.text = "changed"

    def test_json_roundtrip(self):
        f = PrivacyFinding(entity_type="EMAIL", start=5, end=25, text="a@b.com", score=0.99)
        restored = PrivacyFinding.model_validate_json(f.model_dump_json())
        assert restored == f


class TestTokenMapping:
    def test_create(self):
        m = TokenMapping(token="PERSON_001", original="John Doe", entity_type="PERSON")
        assert m.token == "PERSON_001"
        assert m.original == "John Doe"

    def test_frozen(self):
        m = TokenMapping(token="X", original="Y", entity_type="Z")
        with pytest.raises(pydantic.ValidationError):
            m.token = "changed"


class TestAnonymizedText:
    def test_create_with_defaults(self):
        at = AnonymizedText(text="PERSON_001 sent an email")
        assert at.text == "PERSON_001 sent an email"
        assert at.mapping_id != ""
        assert at.findings == []
        assert at.mappings == []

    def test_with_data(self):
        f = PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.9)
        m = TokenMapping(token="PERSON_001", original="John Doe", entity_type="PERSON")
        at = AnonymizedText(text="PERSON_001 sent an email", findings=[f], mappings=[m])
        assert len(at.findings) == 1
        assert len(at.mappings) == 1


class TestAnonymizationResult:
    def test_defaults(self):
        r = AnonymizationResult(document_id="doc-1")
        assert r.anonymized_text == ""
        assert r.risk_score == 0.0
        assert r.mode == "pseudonymize"

    def test_with_data(self):
        r = AnonymizationResult(
            document_id="doc-1",
            anonymized_text="PERSON_001 signed contract",
            risk_score=0.45,
            mode="pseudonymize",
        )
        assert r.risk_score == 0.45

    def test_json_roundtrip(self):
        r = AnonymizationResult(document_id="doc-1", anonymized_text="test", risk_score=0.3)
        restored = AnonymizationResult.model_validate_json(r.model_dump_json())
        assert restored.document_id == r.document_id


class TestPrivacyPolicy:
    def test_defaults(self):
        p = PrivacyPolicy()
        assert p.anonymize_before_llm is True
        assert p.mode == AnonymizationMode.PSEUDONYMIZE
        assert p.reversible is True
        assert p.fail_closed is True
        assert "PERSON" in p.entities

    def test_reversible_requires_pseudonymize(self):
        with pytest.raises(pydantic.ValidationError, match="reversible"):
            PrivacyPolicy(mode=AnonymizationMode.REDACT, reversible=True)

    def test_non_reversible_allows_any_mode(self):
        p = PrivacyPolicy(mode=AnonymizationMode.REDACT, reversible=False)
        assert p.mode == AnonymizationMode.REDACT

    def test_custom_entities(self):
        p = PrivacyPolicy(entities=["PERSON", "IBAN_CODE"])
        assert len(p.entities) == 2


class TestPrivacyErrors:
    def test_privacy_error_hierarchy(self):
        assert issubclass(PrivacyError, DocflowError)
        assert issubclass(AnonymizationError, PrivacyError)

    def test_can_raise(self):
        with pytest.raises(PrivacyError):
            raise AnonymizationError("anonymization failed")
