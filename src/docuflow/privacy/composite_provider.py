from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping

if TYPE_CHECKING:
    from docuflow.privacy.provider import PrivacyProvider


class CompositeProvider:
    """Runs multiple PrivacyProviders and merges their findings into one detection pass.

    Typical use: PresidioProvider for PII plus a DictionaryProvider for
    company-specific terms, so PrivacyPolicy only needs one provider.

        CompositeProvider([PresidioProvider(), DictionaryProvider(mask={"Acme Corp": "ORG"})])

    Findings from different sub-providers are not deduplicated or checked for
    overlap, matching the existing single-provider behavior.
    """

    def __init__(self, providers: list[PrivacyProvider]):
        if not providers:
            raise ValueError("CompositeProvider requires at least one provider")
        self.providers = providers

    async def adetect_text(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> list[PrivacyFinding]:
        results = await asyncio.gather(*[
            p.adetect_text(text, entities=entities, language=language, score_threshold=score_threshold)
            for p in self.providers
        ])
        findings: list[PrivacyFinding] = []
        for r in results:
            findings.extend(r)
        return findings

    async def aanonymize_text(
        self,
        text: str,
        findings: list[PrivacyFinding],
        mode: AnonymizationMode,
        token_map: dict[str, str] | None = None,
    ) -> tuple[str, list[TokenMapping]]:
        if not findings:
            return text, []

        sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)
        result = text
        mappings: list[TokenMapping] = []

        for finding in sorted_findings:
            original = finding.text

            if finding.replacement is not None:
                replacement = finding.replacement
            elif mode == AnonymizationMode.REDACT:
                replacement = "[REDACTED]"
            elif mode == AnonymizationMode.MASK:
                replacement = "*" if len(original) <= 1 else original[0] + "*" * (len(original) - 1)
            elif mode == AnonymizationMode.PSEUDONYMIZE:
                replacement = (token_map or {}).get(original, f"{finding.entity_type}_???")
            elif mode == AnonymizationMode.HASH:
                replacement = hashlib.sha256(original.encode()).hexdigest()[:16]
            else:
                replacement = "[REDACTED]"

            if mode == AnonymizationMode.PSEUDONYMIZE:
                mappings.append(
                    TokenMapping(token=replacement, original=original, entity_type=finding.entity_type)
                )

            result = result[: finding.start] + replacement + result[finding.end :]

        return result, mappings

    async def arestore_text(self, text: str, mappings: list[TokenMapping]) -> str:
        result = text
        sorted_mappings = sorted(mappings, key=lambda m: len(m.token), reverse=True)
        for mapping in sorted_mappings:
            result = result.replace(mapping.token, mapping.original)
        return result
