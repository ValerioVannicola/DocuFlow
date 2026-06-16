from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from docuflow._sync import run_sync
from docuflow.observability.traces import Trace
from docuflow.workflow.state import PipelineState
from docuflow.workflow.steps import PipelineStep


@dataclass
class PipelineResult:
    """Result returned by the low-level manual pipeline runner."""

    state: PipelineState
    trace: Trace
    duration_ms: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)


class Pipeline:
    """Run an explicit sequence of pipeline steps.

    Users reach for this when they want to compose ingestion, parsing,
    extraction, review, storage, or custom steps manually instead of using
    :class:`docuflow.processor.DocumentPipeline`.

    Args:
        steps: Ordered list of pipeline steps to execute.
    """

    def __init__(self, steps: list[PipelineStep]):
        self.steps = steps

    def _find_storage(self) -> Any:
        from docuflow.workflow.steps import Store

        for step in self.steps:
            if isinstance(step, Store) and step.storage is not None:
                return step.storage
        return None

    async def _save_on_failure(self, state: PipelineState) -> None:
        storage = self._find_storage()
        if storage is None:
            return
        try:
            if state.document:
                await storage.save_document(state.document)
            if state.extraction_result:
                await storage.save_result(state.extraction_result)
            await storage.save_trace(state.trace)
        except (OSError, ValueError):
            pass

    async def run(
        self,
        input_path: str | None = None,
        schema: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run all configured steps.

        Args:
            input_path: Optional document path stored in pipeline state.
            schema: Optional Pydantic schema stored in pipeline state.
            **kwargs: Extra state metadata forwarded to steps.

        Returns:
            PipelineResult: Final pipeline state, trace, and timing.
        """

        state = PipelineState()
        if input_path:
            state.metadata["input_path"] = input_path
        if schema:
            state.metadata["schema"] = schema
        state.metadata.update(kwargs)

        start = time.monotonic()

        for step in self.steps:
            state.current_step = step.name
            state.status = "running"

            try:
                state = await step.execute(state)
            except Exception as exc:
                state.errors.append(f"Step '{step.name}' failed: {exc}")
                state.status = "failed"
                state.trace.add_event(
                    "error", step_name=step.name, error=str(exc)
                )
                break

            if state.status == "failed":
                break

        if state.status != "failed":
            state.status = "completed"
            state.trace.complete()
        else:
            await self._save_on_failure(state)

        duration_ms = (time.monotonic() - start) * 1000

        return PipelineResult(
            state=state,
            trace=state.trace,
            duration_ms=duration_ms,
            success=state.status == "completed",
            errors=state.errors,
        )

    def run_sync(
        self,
        input_path: str | None = None,
        schema: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Synchronous wrapper for :meth:`run`."""

        return run_sync(self.run(input_path, schema, **kwargs))
