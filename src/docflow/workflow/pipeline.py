from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from docflow._sync import run_sync
from docflow.observability.traces import Trace
from docflow.workflow.state import PipelineState
from docflow.workflow.steps import PipelineStep


@dataclass
class PipelineResult:
    state: PipelineState
    trace: Trace
    duration_ms: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, steps: list[PipelineStep]):
        self.steps = steps

    def _find_storage(self) -> Any:
        from docflow.workflow.steps import Store

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
        return run_sync(self.run(input_path, schema, **kwargs))
