from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping


class DictionaryProvider:
    """PrivacyProvider that detects user-supplied terms instead of relying on PII models.

    Use this for anything Presidio doesn't know about: company names, project
    codenames, internal account/ticket formats, etc. Combine with PresidioProvider
    via CompositeProvider to cover both PII and custom terms in one pass.

    Literal terms (the default) are matched with a single combined regex compiled
    once at construction, so detection is one pass over the text no matter how
    many terms you load — tens of thousands of terms stay fast. ``re.finditer``
    yields non-overlapping, leftmost matches, and terms are ordered longest-first
    so a longer term wins over a shorter overlapping one (e.g. "Acme Corp" beats
    "Acme"); the emitted findings never overlap.

    Args:
        mask: term -> entity_type label. The replacement text is decided by the
            policy's AnonymizationMode (redact/mask/pseudonymize/hash), same as
            Presidio findings.
        replacements: term -> literal replacement text, substituted verbatim
            regardless of mode (e.g. {"Acme Corp": "[CUSTOMER]"}).
        regex: treat dictionary keys as regex patterns instead of literal text.
            Regex keys are matched one pattern at a time (use this only for a
            small number of patterns, not a huge literal list).
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

        # Literal terms share one combined regex, compiled once. Regex keys fall
        # back to the per-pattern scan (only sensible for a handful of patterns).
        self._pattern: re.Pattern | None = None
        self._lookup: dict[str, tuple[str, str | None]] | None = None
        if not regex:
            self._pattern, self._lookup = self._build_literal_matcher()

    @classmethod
    def numbered(
        cls,
        terms: list[str] | None,
        root: str,
        *,
        start: int = 1,
        regex: bool = False,
        case_sensitive: bool = True,
        cache_path: str | Path | None = None,
    ) -> DictionaryProvider:
        """Build a provider mapping each term to ``{root}_{n}`` by list order.

        The first term becomes ``{root}_{start}``, the next ``{root}_{start+1}``,
        and so on — numbering follows the order of ``terms``, not the order the
        terms appear in the document. Each term is registered as a literal
        ``replacements`` entry, so the numbered token is substituted verbatim
        regardless of the policy ``mode``. Duplicate terms keep the number first
        assigned to them.

            DictionaryProvider.numbered(["Acme Corp", "Globex"], root="company")
            # replacements = {"Acme Corp": "company_1", "Globex": "company_2"}

        Persistence (``cache_path``): the generated ``term -> token`` mapping is
        the artifact worth keeping — it fixes the numbering so the same term maps
        to the same token on every run. The first call with a ``cache_path`` that
        does not exist builds the mapping from ``terms`` and writes it there; later
        calls load it straight from that file and ignore ``terms`` (delete the file
        to renumber). The combined matcher is recompiled in-process from the loaded
        mapping — that is a single, fast compile, not a per-term rebuild.

        Args:
            terms: terms to mask, in the order they should be numbered. May be
                None/empty when loading from an existing ``cache_path``.
            root: prefix for the generated tokens (``{root}_{n}``).
            start: first number to assign (default 1).
            regex: treat each term as a regex pattern instead of literal text.
            case_sensitive: whether matching is case-sensitive.
            cache_path: file to persist the generated mapping to (JSON).
        """
        path = Path(cache_path) if cache_path else None

        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                replacements: dict[str, str] = json.load(f)
        else:
            if not terms:
                raise ValueError("DictionaryProvider.numbered() requires a non-empty list of terms")
            replacements = {}
            n = start
            for term in terms:
                if term in replacements:
                    continue
                replacements[term] = f"{root}_{n}"
                n += 1
            if path:
                _atomic_write_json(path, replacements)

        return cls(replacements=replacements, regex=regex, case_sensitive=case_sensitive)

    # -- literal matcher (built once) -------------------------------------

    def _build_literal_matcher(self) -> tuple[re.Pattern | None, dict[str, tuple[str, str | None]]]:
        lookup: dict[str, tuple[str, str | None]] = {}
        for term, label in self.mask.items():
            key = term if self.case_sensitive else term.lower()
            if key:
                lookup[key] = (label, None)
        for term, literal in self.replacements.items():
            key = term if self.case_sensitive else term.lower()
            if key:
                lookup[key] = ("CUSTOM", literal)

        if not lookup:
            return None, lookup

        # Longest-first: at a given position the regex engine takes the first
        # alternative that matches, so ordering longer terms first makes the
        # longer term win over a shorter overlapping one.
        ordered = sorted(lookup.keys(), key=len, reverse=True)
        flags = 0 if self.case_sensitive else re.IGNORECASE
        pattern = re.compile("|".join(re.escape(t) for t in ordered), flags)
        return pattern, lookup

    def _literal_detect(self, text: str) -> list[PrivacyFinding]:
        findings: list[PrivacyFinding] = []
        for m in self._pattern.finditer(text):
            matched = m.group(0)
            key = matched if self.case_sensitive else matched.lower()
            entity_type, replacement = self._lookup[key]
            findings.append(
                PrivacyFinding(
                    entity_type=entity_type,
                    start=m.start(),
                    end=m.end(),
                    text=matched,
                    score=1.0,
                    replacement=replacement,
                )
            )
        return findings

    def _regex_find(
        self, text: str, term: str, entity_type: str, replacement: str | None
    ) -> list[PrivacyFinding]:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        pattern = re.compile(term, flags)
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
        if not self.regex:
            return self._literal_detect(text) if self._pattern is not None else []

        findings: list[PrivacyFinding] = []
        for term, label in self.mask.items():
            findings.extend(self._regex_find(text, term, entity_type=label, replacement=None))
        for term, literal in self.replacements.items():
            findings.extend(self._regex_find(text, term, entity_type="CUSTOM", replacement=literal))
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


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)  # atomic on POSIX/Windows
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
