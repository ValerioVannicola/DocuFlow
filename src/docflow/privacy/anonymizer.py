from __future__ import annotations

import hashlib
import uuid
from typing import Any

from docflow.errors import AnonymizationError
from docflow.privacy.models import (
    AnonymizationMode,
    AnonymizationResult,
    AnonymizedText,
    PrivacyFinding,
    TokenMapping,
)
from docflow.privacy.policy import PrivacyPolicy

HIGH_RISK_ENTITIES = frozenset({
    "IBAN_CODE", "CREDIT_CARD", "US_SSN", "UK_NHS", "US_PASSPORT",
    "US_DRIVER_LICENSE", "MEDICAL_LICENSE", "IP_ADDRESS",
})


class Anonymizer:
    def __init__(self, policy: PrivacyPolicy):
        self.policy = policy
        self.provider = policy.provider
        self.mapping_store = policy.mapping_store
        self._counters: dict[str, dict[str, int]] = {}
        self._value_to_token: dict[str, dict[str, str]] = {}

    def _get_token(self, scope_id: str, entity_type: str, original_value: str) -> str:
        if scope_id not in self._value_to_token:
            self._value_to_token[scope_id] = {}
            self._counters[scope_id] = {}

        key = f"{entity_type}:{original_value}"
        if key in self._value_to_token[scope_id]:
            return self._value_to_token[scope_id][key]

        if entity_type not in self._counters[scope_id]:
            self._counters[scope_id][entity_type] = 0
        self._counters[scope_id][entity_type] += 1
        counter = self._counters[scope_id][entity_type]

        token = f"{entity_type}_{counter:03d}"
        self._value_to_token[scope_id][key] = token
        return token

    def _apply_mode(
        self, text: str, findings: list[PrivacyFinding], scope_id: str
    ) -> tuple[str, list[TokenMapping]]:
        if not findings:
            return text, []

        sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)
        mappings: list[TokenMapping] = []
        result = text

        for finding in sorted_findings:
            original = finding.text
            mode = self.policy.mode

            if mode == AnonymizationMode.REDACT:
                replacement = "[REDACTED]"
            elif mode == AnonymizationMode.MASK:
                replacement = "*" if len(original) <= 1 else original[0] + "*" * (len(original) - 1)
            elif mode == AnonymizationMode.PSEUDONYMIZE:
                replacement = self._get_token(scope_id, finding.entity_type, original)
                mappings.append(
                    TokenMapping(token=replacement, original=original, entity_type=finding.entity_type)
                )
            elif mode == AnonymizationMode.HASH:
                replacement = hashlib.sha256(original.encode()).hexdigest()[:16]
            else:
                replacement = "[REDACTED]"

            result = result[: finding.start] + replacement + result[finding.end :]

        return result, mappings

    async def anonymize_text(
        self, text: str, scope_id: str | None = None
    ) -> AnonymizedText:
        if not text:
            return AnonymizedText(text="")

        scope = scope_id or str(uuid.uuid4())

        try:
            findings = await self.provider.adetect_text(
                text,
                entities=self.policy.entities,
                score_threshold=self.policy.score_threshold,
            )
        except Exception as exc:
            if self.policy.fail_closed:
                raise AnonymizationError(f"PII detection failed: {exc}") from exc
            return AnonymizedText(text=text)

        anonymized_text, mappings = self._apply_mode(text, findings, scope)

        mapping_id = str(uuid.uuid4())
        if self.policy.reversible and mappings and self.mapping_store:
            await self.mapping_store.save_mapping(mapping_id, mappings)

        return AnonymizedText(
            text=anonymized_text,
            mapping_id=mapping_id,
            findings=findings,
            mappings=mappings,
        )

    async def anonymize_document(
        self, document: Any, scope_id: str | None = None
    ) -> AnonymizationResult:
        scope = scope_id or document.id
        all_findings: list[PrivacyFinding] = []
        all_mappings: list[TokenMapping] = []
        page_results: list[AnonymizedText] = []

        for page in document.pages:
            result = await self.anonymize_text(page.text, scope_id=scope)
            page_results.append(result)
            all_findings.extend(result.findings)
            all_mappings.extend(result.mappings)

        anonymized_full = "\n\n".join(pr.text for pr in page_results)
        if not document.pages and document.raw_text:
            single = await self.anonymize_text(document.raw_text, scope_id=scope)
            anonymized_full = single.text
            all_findings.extend(single.findings)
            all_mappings.extend(single.mappings)
            page_results.append(single)

        risk_score = self._calculate_risk_score(
            all_findings, len(document.raw_text) if document.raw_text else 1
        )

        mapping_id = str(uuid.uuid4())
        if self.policy.reversible and all_mappings and self.mapping_store:
            await self.mapping_store.save_mapping(mapping_id, all_mappings)

        return AnonymizationResult(
            document_id=document.id,
            mapping_id=mapping_id,
            anonymized_text=anonymized_full,
            findings=all_findings,
            token_mappings=all_mappings,
            mode=self.policy.mode.value,
            page_results=page_results,
            risk_score=risk_score,
        )

    async def restore_text(self, text: str, mapping_id: str) -> str:
        if not self.mapping_store:
            raise AnonymizationError("No mapping store configured for restoration")

        mappings = await self.mapping_store.load_mapping(mapping_id)
        if mappings is None:
            raise AnonymizationError(f"No mapping found for id: {mapping_id}")

        result = text
        sorted_mappings = sorted(mappings, key=lambda m: len(m.token), reverse=True)
        for mapping in sorted_mappings:
            result = result.replace(mapping.token, mapping.original)
        return result

    async def restore_result(self, result: Any, mapping_id: str) -> Any:
        if not self.mapping_store:
            raise AnonymizationError("No mapping store configured for restoration")

        mappings = await self.mapping_store.load_mapping(mapping_id)
        if mappings is None:
            raise AnonymizationError(f"No mapping found for id: {mapping_id}")

        sorted_mappings = sorted(mappings, key=lambda m: len(m.token), reverse=True)

        restored_data = {}
        for key, value in result.data.items():
            if isinstance(value, str):
                for mapping in sorted_mappings:
                    value = value.replace(mapping.token, mapping.original)
            restored_data[key] = value

        for _field_name, field in result.fields.items():
            if isinstance(field.value, str):
                restored_value = field.value
                for mapping in sorted_mappings:
                    restored_value = restored_value.replace(mapping.token, mapping.original)
                field.value = restored_value

        result.data = restored_data
        return result

    def _calculate_risk_score(
        self, findings: list[PrivacyFinding], text_length: int
    ) -> float:
        if not findings or text_length <= 0:
            return 0.0

        entity_char_count = sum(f.end - f.start for f in findings)
        density = min(entity_char_count / text_length, 1.0)

        high_risk_count = sum(
            1 for f in findings if f.entity_type in HIGH_RISK_ENTITIES
        )
        high_risk_bonus = min(high_risk_count * 0.1, 0.3)

        type_diversity = len({f.entity_type for f in findings})
        diversity_bonus = min(type_diversity * 0.05, 0.2)

        score = density * 0.5 + high_risk_bonus + diversity_bonus
        return min(score, 1.0)
