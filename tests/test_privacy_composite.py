from __future__ import annotations

import pytest

from docuflow.privacy.composite_provider import CompositeProvider
from docuflow.privacy.dictionary_provider import DictionaryProvider
from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping


class _StubProvider:
    def __init__(self, findings: list[PrivacyFinding]):
        self._findings = findings

    async def adetect_text(self, text, entities=None, language="en", score_threshold=0.35):
        return self._findings

    async def aanonymize_text(self, text, findings, mode, token_map=None):
        return text, []

    async def arestore_text(self, text, mappings):
        return text


class TestCompositeProviderDetect:
    async def test_merges_findings_from_all_providers(self):
        presidio_like = _StubProvider(
            [PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.9)]
        )
        dictionary = DictionaryProvider(mask={"Acme Corp": "ORG"})
        provider = CompositeProvider([presidio_like, dictionary])

        findings = await provider.adetect_text("John Doe works at Acme Corp")
        entity_types = sorted(f.entity_type for f in findings)
        assert entity_types == ["ORG", "PERSON"]

    def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError, match="at least one provider"):
            CompositeProvider([])


class TestCompositeProviderAnonymize:
    async def test_anonymize_via_anonymizer(self):
        from docuflow.privacy.anonymizer import Anonymizer
        from docuflow.privacy.policy import PrivacyPolicy

        presidio_like = _StubProvider(
            [PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.9)]
        )
        dictionary = DictionaryProvider(mask={"Acme Corp": "ORG"})
        provider = CompositeProvider([presidio_like, dictionary])
        policy = PrivacyPolicy(mode=AnonymizationMode.REDACT, reversible=False, provider=provider)
        anonymizer = Anonymizer(policy)

        result = await anonymizer.anonymize_text("John Doe works at Acme Corp", scope_id="s")
        assert "John Doe" not in result.text
        assert "Acme Corp" not in result.text
        assert result.text.count("[REDACTED]") == 2

    async def test_replacement_priority_through_composite(self):
        dictionary = DictionaryProvider(replacements={"PRJ-1234": "[PROJECT-CODE]"})
        provider = CompositeProvider([dictionary])
        findings = await provider.adetect_text("Ticket PRJ-1234 open")
        result, mappings = await provider.aanonymize_text(
            "Ticket PRJ-1234 open", findings, AnonymizationMode.HASH
        )
        assert result == "Ticket [PROJECT-CODE] open"

    async def test_restore_text(self):
        provider = CompositeProvider([DictionaryProvider(mask={"Acme": "ORG"})])
        mappings = [TokenMapping(token="ORG_001", original="Acme", entity_type="ORG")]
        result = await provider.arestore_text("ORG_001 signed", mappings)
        assert result == "Acme signed"
