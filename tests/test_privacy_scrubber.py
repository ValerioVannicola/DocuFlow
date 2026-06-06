from __future__ import annotations

from unittest.mock import AsyncMock

from docflow.observability.traces import create_trace
from docflow.privacy.models import PrivacyFinding
from docflow.privacy.scrubber import TraceScrubber


def _make_mock_provider(findings=None):
    provider = AsyncMock()
    if findings:
        provider.adetect_text = AsyncMock(return_value=findings)
    else:
        provider.adetect_text = AsyncMock(return_value=[])
    return provider


class TestTraceScrubber:
    async def test_scrub_text_with_pii(self):
        findings = [
            PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95)
        ]
        provider = _make_mock_provider(findings)
        scrubber = TraceScrubber(provider=provider)
        result = await scrubber.scrub_text("John Doe sent an email")
        assert "John Doe" not in result
        assert "[SCRUBBED]" in result

    async def test_scrub_text_no_pii(self):
        provider = _make_mock_provider([])
        scrubber = TraceScrubber(provider=provider)
        result = await scrubber.scrub_text("no sensitive data")
        assert result == "no sensitive data"

    async def test_scrub_text_empty(self):
        provider = _make_mock_provider([])
        scrubber = TraceScrubber(provider=provider)
        result = await scrubber.scrub_text("")
        assert result == ""

    async def test_scrub_trace(self):
        findings = [
            PrivacyFinding(entity_type="PERSON", start=0, end=8, text="John Doe", score=0.95)
        ]
        provider = _make_mock_provider(findings)
        scrubber = TraceScrubber(provider=provider)

        trace = create_trace("doc-1")
        trace.add_event("extraction", step_name="llm", prompt="John Doe invoice")

        scrubbed = await scrubber.scrub_trace(trace)

        assert scrubbed.trace_id == trace.trace_id
        assert scrubbed.document_id == trace.document_id
        assert len(scrubbed.events) == 1
        scrubbed_prompt = scrubbed.events[0].metadata.get("prompt", "")
        assert "John Doe" not in scrubbed_prompt
        assert "[SCRUBBED]" in scrubbed_prompt

    async def test_scrub_trace_does_not_mutate_original(self):
        findings = [
            PrivacyFinding(
                entity_type="EMAIL",
                start=10,
                end=26,
                text="john@example.com",
                score=0.99,
            )
        ]
        provider = _make_mock_provider(findings)
        scrubber = TraceScrubber(provider=provider)

        trace = create_trace("doc-1")
        trace.add_event("test", prompt="Contact john@example.com for info")

        scrubbed = await scrubber.scrub_trace(trace)

        assert "john@example.com" in trace.events[0].metadata["prompt"]
        assert "john@example.com" not in scrubbed.events[0].metadata["prompt"]

    async def test_scrub_trace_preserves_non_string_metadata(self):
        provider = _make_mock_provider([])
        scrubber = TraceScrubber(provider=provider)

        trace = create_trace("doc-1")
        trace.add_event("test", duration=1500, count=42)

        scrubbed = await scrubber.scrub_trace(trace)
        assert scrubbed.events[0].metadata["duration"] == 1500
        assert scrubbed.events[0].metadata["count"] == 42
