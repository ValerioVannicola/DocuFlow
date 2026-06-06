from __future__ import annotations

from docflow.workflow.pipeline import Pipeline
from docflow.workflow.state import PipelineState
from docflow.workflow.steps import PipelineStep


class MockStep:
    def __init__(self, name: str = "mock", should_fail: bool = False):
        self.name = name
        self.should_fail = should_fail
        self.executed = False

    async def execute(self, state: PipelineState) -> PipelineState:
        self.executed = True
        if self.should_fail:
            state.status = "failed"
            state.errors.append(f"{self.name} failed")
        return state


class ExceptionStep:
    name = "error_step"

    async def execute(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("step exploded")


class TestPipeline:
    async def test_empty_pipeline(self):
        pipeline = Pipeline(steps=[])
        result = await pipeline.run()
        assert result.success
        assert result.state.status == "completed"

    async def test_single_step(self):
        step = MockStep("test_step")
        pipeline = Pipeline(steps=[step])
        result = await pipeline.run()
        assert result.success
        assert step.executed

    async def test_multiple_steps(self):
        steps = [MockStep("step1"), MockStep("step2"), MockStep("step3")]
        pipeline = Pipeline(steps=steps)
        result = await pipeline.run()
        assert result.success
        assert all(s.executed for s in steps)

    async def test_step_failure_stops_pipeline(self):
        steps = [MockStep("ok"), MockStep("bad", should_fail=True), MockStep("after")]
        pipeline = Pipeline(steps=steps)
        result = await pipeline.run()
        assert not result.success
        assert steps[0].executed
        assert steps[1].executed
        assert not steps[2].executed

    async def test_exception_in_step(self):
        pipeline = Pipeline(steps=[MockStep("ok"), ExceptionStep()])
        result = await pipeline.run()
        assert not result.success
        assert "step exploded" in result.errors[0]

    async def test_trace_has_events_for_steps(self):
        step = MockStep("traced_step")
        pipeline = Pipeline(steps=[step])
        result = await pipeline.run()
        assert result.trace is not None

    async def test_input_path_in_metadata(self):
        pipeline = Pipeline(steps=[])
        result = await pipeline.run(input_path="test.pdf")
        assert result.state.metadata["input_path"] == "test.pdf"

    async def test_duration_recorded(self):
        pipeline = Pipeline(steps=[MockStep("fast")])
        result = await pipeline.run()
        assert result.duration_ms >= 0

    def test_run_sync(self):
        pipeline = Pipeline(steps=[MockStep("sync_step")])
        result = pipeline.run_sync()
        assert result.success

    def test_protocol_compliance(self):
        assert isinstance(MockStep(), PipelineStep)


class TestPipelineState:
    def test_defaults(self):
        state = PipelineState()
        assert state.document is None
        assert state.extraction_result is None
        assert state.status == "pending"
        assert state.errors == []
