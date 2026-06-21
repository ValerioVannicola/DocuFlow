from __future__ import annotations

import hashlib
import re

from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping


class DictionaryProvider:
    """PrivacyProvider that detects user-supplied terms instead of relying on PII models.

    Use this for anything Presidio doesn't know about: company names, project
    codenames, internal account/ticket formats, etc. Combine with PresidioProvider
    via CompositeProvider to cover both PII and custom terms in one pass.

    Args:
        mask: term/pattern -> entity_type label. The replacement text is decided
            by the policy's AnonymizationMode (redact/mask/pseudonymize/hash),
            same as Presidio findings.
        replacements: term/pattern -> literal replacement text, substituted
            verbatim regardless of mode (e.g. {"Acme Corp": "[CUSTOMER]"}).
        regex: treat dictionary keys as regex patterns instead of literal text.
        case_sensitive: whether matching is case-sensitive.

    Note: unlike PresidioProvider, the `entities` filter passed by PrivacyPolicy
    is ignored — the keys you provide are already an explicit allowlist.
    """

    def __init__(
        self,
        mask: dict[str, str] | None = None,
        replacements: dict[str, str] | None = None,
        *,
        regex: bool = False,
        case_sensitive: bool = True,
    ):
        if not mask and not replacements:
            raise ValueError("DictionaryProvider requires at least one of `mask` or `replacements`")
        self.mask = mask or {}
        self.replacements = replacements or {}
        self.regex = regex
        self.case_sensitive = case_sensitive

    def _find(
        self, text: str, term: str, entity_type: str, replacement: str | None
    ) -> list[PrivacyFinding]:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        pattern = re.compile(term if self.regex else re.escape(term), flags)
        return [
            PrivacyFinding(
                entity_type=entity_type,
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                score=1.0,
                replacement=replacement,
            )
            for m in pattern.finditer(text)
        ]

    async def adetect_text(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> list[PrivacyFinding]:
        findings: list[PrivacyFinding] = []
        for term, label in self.mask.items():
            findings.extend(self._find(text, term, entity_type=label, replacement=None))
        for term, literal in self.replacements.items():
            findings.extend(self._find(text, term, entity_type="CUSTOM", replacement=literal))
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
