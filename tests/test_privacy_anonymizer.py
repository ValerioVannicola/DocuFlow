from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from docflow.documents.models import Document, DocumentMetadata, Page
from docflow.errors import AnonymizationError
from docflow.privacy.anonymizer import Anonymizer
from docflow.privacy.mapping_store import LocalMappingStore
from docflow.privacy.models import (
    AnonymizationMode,
    AnonymizationResult,
    PrivacyFinding,
)
from docflow.privacy.policy import PrivacyPolicy


class MockProvider:
    def __init__(self, findings: list[PrivacyFinding] | None = None):
        self._findings = findings or []

    async def adetect_text(self, text, entities=None, language="en", score_threshold=0.35):
        result = []
        for f in self._findings:
            if f.text in text:
                idx = text.index(f.text)
                result.append(
                    PrivacyFinding(
                        entity_type=f.entity_type,
                        start=idx,
                        end=idx + len(f.text),
                        text=f.text,
                        score=f.score,
                    )
                )
        return result

    async def aanonymize_text(self, text, findings, mode, token_map=None):
        return text, []

    async def arestore_text(self, text, mappings):
        result = text
        for m in mappings:
            result = result.replace(m.token, m.original)
        return result


def _make_findings() -> list[PrivacyFinding]:
    return [
        PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95),
        PrivacyFinding(entity_type="EMAIL_ADDRESS", start=20, end=36, text="john@example.com", score=0.99),
    ]


def _make_doc(text: str = "John Doe sent email john@example.com about the contract") -> Document:
    return Document(
        id="doc-test",
        metadata=DocumentMetadata(
            file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
        ),
        pages=[Page(page_number=0, text=text)],
        raw_text=text,
    )


class TestAnonymizerPseudonymize:
    async def test_basic_pseudonymize(self, tmp_path):
        provider = MockProvider(_make_findings())
        store = LocalMappingStore(str(tmp_path / "maps"))
        policy = PrivacyPolicy(
            mode=AnonymizationMode.PSEUDONYMIZE,
            reversible=True,
            provider=provider,
            mapping_store=store,
        )
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text(
            "John Doe sent email john@example.com about the contract",
            scope_id="test-scope",
        )
        assert "John Doe" not in result.text
        assert "PERSON_001" in result.text
        assert "EMAIL_ADDRESS_001" in result.text
        assert len(result.mappings) == 2

    async def test_pseudonymize_stability(self, tmp_path):
        provider = MockProvider(_make_findings())
        store = LocalMappingStore(str(tmp_path / "maps"))
        policy = PrivacyPolicy(provider=provider, mapping_store=store)
        anonymizer = Anonymizer(policy)

        r1 = await anonymizer.anonymize_text("John Doe is here", scope_id="s1")
        r2 = await anonymizer.anonymize_text("John Doe again", scope_id="s1")
        token1 = next(m.token for m in r1.mappings if m.original == "John Doe")
        token2 = next(m.token for m in r2.mappings if m.original == "John Doe")
        assert token1 == token2


class TestAnonymizerModes:
    async def test_redact_mode(self):
        provider = MockProvider(_make_findings())
        policy = PrivacyPolicy(mode=AnonymizationMode.REDACT, reversible=False, provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text(
            "John Doe sent email john@example.com", scope_id="s"
        )
        assert "[REDACTED]" in result.text
        assert "John Doe" not in result.text

    async def test_mask_mode(self):
        provider = MockProvider(_make_findings())
        policy = PrivacyPolicy(mode=AnonymizationMode.MASK, reversible=False, provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text(
            "John Doe sent email john@example.com", scope_id="s"
        )
        assert "J*******" in result.text

    async def test_hash_mode(self):
        provider = MockProvider(_make_findings())
        policy = PrivacyPolicy(mode=AnonymizationMode.HASH, reversible=False, provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text(
            "John Doe sent email john@example.com", scope_id="s"
        )
        assert "John Doe" not in result.text
        assert len(result.text) > 0


class TestAnonymizerDocument:
    async def test_anonymize_document(self, tmp_path):
        provider = MockProvider(_make_findings())
        store = LocalMappingStore(str(tmp_path / "maps"))
        policy = PrivacyPolicy(provider=provider, mapping_store=store)
        anonymizer = Anonymizer(policy)

        doc = _make_doc()
        result = await anonymizer.anonymize_document(doc)

        assert isinstance(result, AnonymizationResult)
        assert result.document_id == "doc-test"
        assert "John Doe" not in result.anonymized_text
        assert result.risk_score > 0
        assert len(result.page_results) == 1
        assert len(result.findings) > 0


class TestAnonymizerRestore:
    async def test_restore_text_roundtrip(self, tmp_path):
        provider = MockProvider(_make_findings())
        store = LocalMappingStore(str(tmp_path / "maps"))
        policy = PrivacyPolicy(provider=provider, mapping_store=store)
        anonymizer = Anonymizer(policy)

        original = "John Doe sent email john@example.com about the contract"
        anon = await anonymizer.anonymize_text(original, scope_id="s1")
        restored = await anonymizer.restore_text(anon.text, anon.mapping_id)
        assert restored == original

    async def test_restore_without_store_raises(self):
        provider = MockProvider()
        policy = PrivacyPolicy(provider=provider, mapping_store=None)
        anonymizer = Anonymizer(policy)
        with pytest.raises(AnonymizationError, match="No mapping store"):
            await anonymizer.restore_text("text", "some-id")


class TestAnonymizerRiskScore:
    def test_no_findings(self):
        policy = PrivacyPolicy(provider=MockProvider())
        anonymizer = Anonymizer(policy)
        assert anonymizer._calculate_risk_score([], 100) == 0.0

    def test_high_risk_entities(self):
        findings = [
            PrivacyFinding(entity_type="IBAN_CODE", start=0, end=20, text="DE89370400440532013000", score=0.99),
            PrivacyFinding(entity_type="CREDIT_CARD", start=25, end=44, text="4111111111111111111", score=0.99),
        ]
        policy = PrivacyPolicy(provider=MockProvider())
        anonymizer = Anonymizer(policy)
        score = anonymizer._calculate_risk_score(findings, 100)
        assert score > 0.3

    def test_low_density(self):
        findings = [
            PrivacyFinding(entity_type="PERSON", start=0, end=4, text="John", score=0.9),
        ]
        policy = PrivacyPolicy(provider=MockProvider())
        anonymizer = Anonymizer(policy)
        score = anonymizer._calculate_risk_score(findings, 1000)
        assert score < 0.2


class TestAnonymizerFailClosed:
    async def test_fail_closed_on_detection_error(self):
        provider = AsyncMock()
        provider.adetect_text = AsyncMock(side_effect=RuntimeError("provider down"))
        policy = PrivacyPolicy(provider=provider, fail_closed=True)
        anonymizer = Anonymizer(policy)
        with pytest.raises(AnonymizationError, match="PII detection failed"):
            await anonymizer.anonymize_text("some text", scope_id="s")

    async def test_fail_open_on_detection_error(self):
        provider = AsyncMock()
        provider.adetect_text = AsyncMock(side_effect=RuntimeError("provider down"))
        policy = PrivacyPolicy(provider=provider, fail_closed=False)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text("some text", scope_id="s")
        assert result.text == "some text"


class TestAnonymizerEmptyInput:
    async def test_empty_text(self):
        policy = PrivacyPolicy(provider=MockProvider())
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text("", scope_id="s")
        assert result.text == ""

    async def test_no_pii_found(self):
        provider = MockProvider([])
        policy = PrivacyPolicy(provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text("no sensitive data here", scope_id="s")
        assert result.text == "no sensitive data here"
        assert result.mappings == []
