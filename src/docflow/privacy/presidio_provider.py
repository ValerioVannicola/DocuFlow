from __future__ import annotations

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from docflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping

_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _ensure_presidio() -> tuple[Any, Any]:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError as e:
        raise ImportError(
            "presidio-analyzer and presidio-anonymizer are required. "
            "Install with: pip install docflow[privacy]"
        ) from e
    return AnalyzerEngine, AnonymizerEngine


def _detect_sync(
    text: str,
    entities: list[str] | None,
    language: str,
    score_threshold: float,
    analyzer: Any,
) -> list[PrivacyFinding]:
    results = analyzer.analyze(
        text=text,
        entities=entities or None,
        language=language,
        score_threshold=score_threshold,
    )
    return [
        PrivacyFinding(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            text=text[r.start : r.end],
            score=r.score,
        )
        for r in results
    ]


class PresidioProvider:
    def __init__(self, language: str = "en", model: str | None = None):
        self.language = language
        self._model = model
        self._analyzer: Any = None
        self._anonymizer: Any = None

    def _ensure_initialized(self) -> None:
        if self._analyzer is not None:
            return
        analyzer_cls, anonymizer_cls = _ensure_presidio()
        self._analyzer = analyzer_cls()
        self._anonymizer = anonymizer_cls()

    async def adetect_text(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> list[PrivacyFinding]:
        self._ensure_initialized()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _EXECUTOR,
            partial(_detect_sync, text, entities, language, score_threshold, self._analyzer),
        )

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

            if mode == AnonymizationMode.REDACT:
                replacement = "[REDACTED]"
            elif mode == AnonymizationMode.MASK:
                replacement = (
                    "*" if len(original) <= 1
                    else original[0] + "*" * (len(original) - 1)
                )
            elif mode == AnonymizationMode.PSEUDONYMIZE:
                replacement = (token_map or {}).get(
                    original, f"{finding.entity_type}_???"
                )
                mappings.append(
                    TokenMapping(
                        token=replacement,
                        original=original,
                        entity_type=finding.entity_type,
                    )
                )
            elif mode == AnonymizationMode.HASH:
                replacement = hashlib.sha256(original.encode()).hexdigest()[:16]
            else:
                replacement = "[REDACTED]"

            result = result[: finding.start] + replacement + result[finding.end :]

        return result, mappings

    async def arestore_text(
        self,
        text: str,
        mappings: list[TokenMapping],
    ) -> str:
        result = text
        sorted_mappings = sorted(
            mappings, key=lambda m: len(m.token), reverse=True
        )
        for mapping in sorted_mappings:
            result = result.replace(mapping.token, mapping.original)
        return result
