from __future__ import annotations

from docflow.observability.traces import Trace, TraceEvent
from docflow.privacy.provider import PrivacyProvider


class TraceScrubber:
    def __init__(
        self,
        provider: PrivacyProvider,
        entities: list[str] | None = None,
    ):
        self.provider = provider
        self.entities = entities

    async def scrub_text(self, text: str) -> str:
        if not text:
            return text
        findings = await self.provider.adetect_text(
            text, entities=self.entities
        )
        if not findings:
            return text
        result = text
        for finding in sorted(findings, key=lambda f: f.start, reverse=True):
            result = result[: finding.start] + "[SCRUBBED]" + result[finding.end :]
        return result

    async def scrub_trace(self, trace: Trace) -> Trace:
        scrubbed_events: list[TraceEvent] = []
        for event in trace.events:
            scrubbed_meta = {}
            for key, value in event.metadata.items():
                if isinstance(value, str):
                    scrubbed_meta[key] = await self.scrub_text(value)
                else:
                    scrubbed_meta[key] = value
            scrubbed_events.append(
                TraceEvent(
                    timestamp=event.timestamp,
                    event_type=event.event_type,
                    step_name=event.step_name,
                    duration_ms=event.duration_ms,
                    metadata=scrubbed_meta,
                )
            )
        return Trace(
            trace_id=trace.trace_id,
            document_id=trace.document_id,
            events=scrubbed_events,
            started_at=trace.started_at,
            completed_at=trace.completed_at,
        )
