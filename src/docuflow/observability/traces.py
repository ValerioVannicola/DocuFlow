from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    step_name: str = ""
    duration_ms: float | None = None
    metadata: dict = Field(default_factory=dict)


class Trace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    events: list[TraceEvent] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None

    def add_event(
        self,
        event_type: str,
        step_name: str = "",
        duration_ms: float | None = None,
        **metadata: object,
    ) -> None:
        self.events.append(
            TraceEvent(
                event_type=event_type,
                step_name=step_name,
                duration_ms=duration_ms,
                metadata=metadata,
            )
        )

    def complete(self) -> None:
        self.completed_at = datetime.now()


def create_trace(document_id: str) -> Trace:
    return Trace(document_id=document_id)
