from __future__ import annotations

import pytest

from docuflow.privacy.dictionary_provider import DictionaryProvider
from docuflow.privacy.models import AnonymizationMode, TokenMapping


class TestDictionaryProviderDetect:
    async def test_label_entries_use_entity_type(self):
        provider = DictionaryProvider(mask={"Acme Corp": "ORG"})
        findings = await provider.adetect_text("Acme Corp signed the contract")
        assert len(findings) == 1
        assert findings[0].entity_type == "ORG"
        assert findings[0].text == "Acme Corp"
        assert findings[0].replacement is None

    async def test_replacement_entries_carry_literal_text(self):
        provider = DictionaryProvider(replacements={"PRJ-1234": "[PROJECT-CODE]"})
        findings = await provider.adetect_text("See PRJ-1234 for details")
        assert len(findings) == 1
        assert findings[0].entity_type == "CUSTOM"
        assert findings[0].replacement == "[PROJECT-CODE]"

    async def test_multiple_occurrences_all_found(self):
        provider = DictionaryProvider(mask={"Acme": "ORG"})
        findings = await provider.adetect_text("Acme met Acme again")
        assert len(findings) == 2

    async def test_no_match_returns_empty(self):
        provider = DictionaryProvider(mask={"Acme Corp": "ORG"})
        findings = await provider.adetect_text("nothing relevant here")
        assert findings == []

    async def test_case_insensitive(self):
        provider = DictionaryProvider(mask={"acme corp": "ORG"}, case_sensitive=False)
        findings = await provider.adetect_text("ACME CORP signed it")
        assert len(findings) == 1
        assert findings[0].text == "ACME CORP"

    async def test_regex_patterns(self):
        provider = DictionaryProvider(mask={r"PRJ-\d{4}": "PROJECT_CODE"}, regex=True)
        findings = await provider.adetect_text("Tickets PRJ-1234 and PRJ-5678")
        assert len(findings) == 2
        assert {f.text for f in findings} == {"PRJ-1234", "PRJ-5678"}

    async def test_literal_term_not_treated_as_regex_by_default(self):
        provider = DictionaryProvider(mask={"a.b": "TOKEN"})
        findings = await provider.adetect_text("a.b matches, axb should not")
        assert len(findings) == 1
        assert findings[0].text == "a.b"

    async def test_entities_filter_is_ignored(self):
        provider = DictionaryProvider(mask={"Acme Corp": "ORG"})
        findings = await provider.adetect_text("Acme Corp here", entities=["PERSON"])
        assert len(findings) == 1

    def test_requires_mask_or_replacements(self):
        with pytest.raises(ValueError, match="requires at least one"):
            DictionaryProvider()


class TestDictionaryProviderAnonymize:
    async def test_replacement_overrides_mode(self):
        provider = DictionaryProvider(replacements={"PRJ-1234": "[PROJECT-CODE]"})
        findings = await provider.adetect_text("See PRJ-1234 now")
        result, mappings = await provider.aanonymize_text(
            "See PRJ-1234 now", findings, AnonymizationMode.HASH
        )
        assert result == "See [PROJECT-CODE] now"
        assert mappings == []

    async def test_label_entry_uses_redact_mode(self):
        provider = DictionaryProvider(mask={"Acme Corp": "ORG"})
        findings = await provider.adetect_text("Acme Corp signed")
        result, mappings = await provider.aanonymize_text(
            "Acme Corp signed", findings, AnonymizationMode.REDACT
        )
        assert result == "[REDACTED] signed"

    async def test_label_entry_uses_mask_mode(self):
        provider = DictionaryProvider(mask={"Acme": "ORG"})
        findings = await provider.adetect_text("Acme signed")
        result, _ = await provider.aanonymize_text("Acme signed", findings, AnonymizationMode.MASK)
        assert result == "A*** signed"

    async def test_no_findings_returns_text_unchanged(self):
        provider = DictionaryProvider(mask={"Acme": "ORG"})
        result, mappings = await provider.aanonymize_text("clean", [], AnonymizationMode.REDACT)
        assert result == "clean"
        assert mappings == []

    async def test_restore_text(self):
        provider = DictionaryProvider(mask={"Acme": "ORG"})
        mappings = [TokenMapping(token="ORG_001", original="Acme", entity_type="ORG")]
        result = await provider.arestore_text("ORG_001 signed", mappings)
        assert result == "Acme signed"


class TestDictionaryProviderViaAnonymizer:
    async def test_anonymizer_honors_literal_replacement(self):
        from docuflow.privacy.anonymizer import Anonymizer
        from docuflow.privacy.policy import PrivacyPolicy

        provider = DictionaryProvider(replacements={"PRJ-1234": "[PROJECT-CODE]"})
        policy = PrivacyPolicy(mode=AnonymizationMode.HASH, reversible=False, provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text("Ticket PRJ-1234 is open", scope_id="s")
        assert result.text == "Ticket [PROJECT-CODE] is open"

    async def test_anonymizer_pseudonymize_records_mapping_for_replacement(self):
        from docuflow.privacy.anonymizer import Anonymizer
        from docuflow.privacy.policy import PrivacyPolicy

        provider = DictionaryProvider(replacements={"PRJ-1234": "[PROJECT-CODE]"})
        policy = PrivacyPolicy(mode=AnonymizationMode.PSEUDONYMIZE, reversible=True, provider=provider)
        anonymizer = Anonymizer(policy)
        result = await anonymizer.anonymize_text("Ticket PRJ-1234 is open", scope_id="s")
        assert result.text == "Ticket [PROJECT-CODE] is open"
        assert len(result.mappings) == 1
        assert result.mappings[0].token == "[PROJECT-CODE]"
        assert result.mappings[0].original == "PRJ-1234"
