from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping


def _make_mock_presidio():
    mock_analyzer_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.entity_type = "PERSON"
    mock_result.start = 0
    mock_result.end = 8
    mock_result.score = 0.95
    mock_analyzer_engine.return_value.analyze.return_value = [mock_result]

    mock_anonymizer_engine = MagicMock()

    mock_analyzer_module = MagicMock()
    mock_analyzer_module.AnalyzerEngine = mock_analyzer_engine

    mock_anonymizer_module = MagicMock()
    mock_anonymizer_module.AnonymizerEngine = mock_anonymizer_engine

    return mock_analyzer_module, mock_anonymizer_module


class TestPresidioProvider:
    async def test_detect_text(self):
        mock_analyzer, mock_anonymizer = _make_mock_presidio()

        with patch.dict(sys.modules, {
            "presidio_analyzer": mock_analyzer,
            "presidio_anonymizer": mock_anonymizer,
        }):
            if "docuflow.privacy.presidio_provider" in sys.modules:
                del sys.modules["docuflow.privacy.presidio_provider"]
            from docuflow.privacy.presidio_provider import PresidioProvider

            provider = PresidioProvider()
            findings = await provider.adetect_text("John Doe sent an email")

        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON"
        assert findings[0].start == 0
        assert findings[0].end == 8
        assert findings[0].score == 0.95

    async def test_anonymize_redact(self):
        from docuflow.privacy.presidio_provider import PresidioProvider

        provider = PresidioProvider.__new__(PresidioProvider)
        provider.language = "en"
        provider._model = None
        provider._analyzer = None
        provider._anonymizer = None

        findings = [
            PrivacyFinding(
                entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95
            ),
        ]
        result, mappings = await provider.aanonymize_text(
            "John Doe is here", findings, AnonymizationMode.REDACT
        )
        assert result == "[REDACTED] is here"
        assert mappings == []

    async def test_anonymize_pseudonymize_with_token_map(self):
        from docuflow.privacy.presidio_provider import PresidioProvider

        provider = PresidioProvider.__new__(PresidioProvider)
        provider.language = "en"
        provider._model = None
        provider._analyzer = None
        provider._anonymizer = None

        findings = [
            PrivacyFinding(
                entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95
            ),
        ]
        result, mappings = await provider.aanonymize_text(
            "John Doe is here",
            findings,
            AnonymizationMode.PSEUDONYMIZE,
            token_map={"John Doe": "PERSON_001"},
        )
        assert result == "PERSON_001 is here"
        assert len(mappings) == 1
        assert mappings[0].token == "PERSON_001"

    async def test_anonymize_no_findings(self):
        from docuflow.privacy.presidio_provider import PresidioProvider

        provider = PresidioProvider.__new__(PresidioProvider)
        provider.language = "en"
        provider._model = None
        provider._analyzer = None
        provider._anonymizer = None

        result, mappings = await provider.aanonymize_text(
            "clean text", [], AnonymizationMode.REDACT
        )
        assert result == "clean text"
        assert mappings == []

    async def test_restore_text(self):
        from docuflow.privacy.presidio_provider import PresidioProvider

        provider = PresidioProvider.__new__(PresidioProvider)
        provider.language = "en"
        provider._model = None
        provider._analyzer = None
        provider._anonymizer = None

        mappings = [
            TokenMapping(
                token="PERSON_001", original="John Doe", entity_type="PERSON"
            ),
        ]
        result = await provider.arestore_text("PERSON_001 is here", mappings)
        assert result == "John Doe is here"

    def test_import_error_message(self):
        with patch.dict(sys.modules, {
            "presidio_analyzer": None,
            "presidio_anonymizer": None,
        }):
            if "docuflow.privacy.presidio_provider" in sys.modules:
                del sys.modules["docuflow.privacy.presidio_provider"]
            from docuflow.privacy.presidio_provider import _ensure_presidio

            with pytest.raises(ImportError, match="presidio-analyzer"):
                _ensure_presidio()
