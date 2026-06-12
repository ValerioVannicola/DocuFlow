from __future__ import annotations

from unittest.mock import AsyncMock, patch

from docuflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
    Word,
)
from docuflow.extraction.escalation import EscalationPolicy, evaluate_escalation
from docuflow.extraction.models import ExtractionResult


def _word(text: str, conf: float | None) -> Word:
    return Word(text=text, bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10), confidence=conf)


def _ocr_doc(confs: list[float], words_per_page_text: str | None = None) -> Document:
    words = [_word(f"w{i}", c) for i, c in enumerate(confs)]
    text = words_per_page_text or " ".join(
        f"word{i} something here padding" for i in range(len(confs))
    )
    return Document(
        id="d1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=[
            Page(
                page_number=0,
                blocks=[
                    Block(
                        block_id="b1",
                        block_type=BlockType.TEXT,
                        text=text,
                        confidence=sum(confs) / len(confs) if confs else None,
                        words=words,
                    )
                ],
                text=text,
            )
        ],
        raw_text=text,
    )


def _native_doc(text: str) -> Document:
    return Document(
        id="d1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=[
            Page(
                page_number=0,
                blocks=[Block(block_id="b1", block_type=BlockType.TEXT, text=text)],
                text=text,
            )
        ],
        raw_text=text,
    )


class TestEvaluateEscalation:
    def test_good_ocr_no_escalation(self):
        doc = _ocr_doc([0.95, 0.92, 0.9, 0.88])
        escalate, reason = evaluate_escalation(doc)
        assert not escalate
        assert "acceptable" in reason

    def test_low_mean_confidence_escalates(self):
        doc = _ocr_doc([0.4, 0.3, 0.5, 0.45])
        escalate, reason = evaluate_escalation(doc)
        assert escalate
        assert "below" in reason

    def test_high_low_confidence_ratio_escalates(self):
        # mean is above 0.6 but half the words are unreliable
        doc = _ocr_doc([0.95, 0.95, 0.95, 0.4, 0.4, 0.4])
        escalate, reason = evaluate_escalation(doc)
        assert escalate
        assert "%" in reason

    def test_native_text_never_escalates(self):
        doc = _native_doc(
            "A perfectly normal digital invoice with plenty of readable text content."
        )
        escalate, reason = evaluate_escalation(doc)
        assert not escalate
        assert "native" in reason

    def test_empty_document_escalates(self):
        doc = _native_doc("x")
        escalate, reason = evaluate_escalation(doc)
        assert escalate
        assert "no usable text" in reason

    def test_custom_thresholds(self):
        doc = _ocr_doc([0.7, 0.7, 0.7, 0.7])
        assert not evaluate_escalation(doc)[0]
        strict = EscalationPolicy(min_ocr_score=0.8)
        assert evaluate_escalation(doc, strict)[0]


class TestExtractAutoStep:
    def _state(self, document: Document):
        from docuflow.workflow.state import PipelineState

        state = PipelineState()
        state.document = document
        return state

    def _schema(self):
        from pydantic import BaseModel

        class Invoice(BaseModel):
            total: float

        return Invoice

    def _result(self) -> ExtractionResult:
        return ExtractionResult(document_id="d1", schema_name="Invoice")

    async def test_good_ocr_uses_text_engine(self):
        from docuflow.workflow.steps import ExtractAuto

        step = ExtractAuto(schema=self._schema(), llm=AsyncMock())
        state = self._state(_ocr_doc([0.95, 0.9, 0.92, 0.9]))

        with patch(
            "docuflow.extraction.engine.ExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as text_extract, patch(
            "docuflow.extraction.engine.VisionExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as vision_extract:
            state = await step.execute(state)

        assert text_extract.called
        assert not vision_extract.called
        assert state.extraction_result.escalated is False

    async def test_poor_ocr_escalates_to_vision(self):
        from docuflow.workflow.steps import ExtractAuto

        step = ExtractAuto(schema=self._schema(), llm=AsyncMock())
        state = self._state(_ocr_doc([0.4, 0.35, 0.3, 0.45]))

        with patch(
            "docuflow.extraction.engine.ExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as text_extract, patch(
            "docuflow.extraction.engine.VisionExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as vision_extract:
            state = await step.execute(state)

        assert vision_extract.called
        assert not text_extract.called
        assert state.extraction_result.escalated is True
        assert "below" in state.extraction_result.escalation_reason
        events = [e.event_type for e in state.trace.events]
        assert "vision_escalation" in events

    async def test_escalation_to_hybrid(self):
        from docuflow.workflow.steps import ExtractAuto

        step = ExtractAuto(
            schema=self._schema(), llm=AsyncMock(),
            policy=EscalationPolicy(escalate_to="hybrid"),
        )
        state = self._state(_ocr_doc([0.4, 0.35, 0.3, 0.45]))

        with patch(
            "docuflow.extraction.engine.HybridExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as hybrid_extract:
            state = await step.execute(state)

        assert hybrid_extract.called
        assert state.extraction_result.escalated is True

    async def test_privacy_suppresses_escalation(self):
        from docuflow.workflow.steps import ExtractAuto

        step = ExtractAuto(
            schema=self._schema(), llm=AsyncMock(), allow_escalation=False,
        )
        state = self._state(_ocr_doc([0.4, 0.35, 0.3, 0.45]))

        with patch(
            "docuflow.extraction.engine.ExtractionEngine.extract",
            new=AsyncMock(return_value=self._result()),
        ) as text_extract:
            state = await step.execute(state)

        assert text_extract.called
        assert state.extraction_result.escalated is False
        events = [e.event_type for e in state.trace.events]
        assert "vision_escalation_suppressed" in events


class TestDocumentPipelineAuto:
    def test_auto_with_parser_is_allowed(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(extraction_type="auto", parser="smart")
        assert pipeline._extraction_type == "auto"

    def test_auto_accepts_escalation_thresholds(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            extraction_type="auto",
            escalation={"min_ocr_score": 0.75, "escalate_to": "hybrid"},
        )
        assert pipeline._escalation["min_ocr_score"] == 0.75

    def test_workflow_config_accepts_escalation(self):
        from docuflow.workflow_config import load_workflow_config

        cfg = load_workflow_config({
            "name": "claims",
            "schema": {"total": {"type": "float"}},
            "extraction_type": "auto",
            "escalation": {"min_ocr_score": 0.7},
        })
        assert cfg.extraction_type == "auto"
        pipeline = cfg.build_pipeline()
        assert pipeline._escalation == {"min_ocr_score": 0.7}
