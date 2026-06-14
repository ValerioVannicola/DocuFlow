from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel

from docuflow.documents.models import (
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
)
from docuflow.extraction.llm.base import LLMResponse
from docuflow.extraction.models import (
    ExtractedField,
    ExtractionResult,
    FieldConsensus,
    FieldTrust,
    OCRFieldConfidence,
    TokenUsage,
)
from docuflow.extraction.verify import (
    VerificationPolicy,
    _crop_region,
    _trigger_reason,
    verify_result,
)


class Invoice(BaseModel):
    supplier_name: str
    total: float


def _field(
    value,
    consensus_ratio: float | None = None,
    ocr_score: float | None = None,
    ocr_method: str = "exact_block",
    bbox: BoundingBox | None = None,
) -> ExtractedField:
    f = ExtractedField(value=value, trust=FieldTrust(found_in_source=True, trust_gate=True))
    if consensus_ratio is not None:
        f.consensus = FieldConsensus(
            n_instances=3, n_succeeded=3,
            agreement=f"{int(consensus_ratio * 3)}/3",
            agreement_ratio=consensus_ratio,
            majority_ratio=consensus_ratio,
        )
    if ocr_score is not None or ocr_method != "exact_block":
        f.ocr = OCRFieldConfidence(
            score=ocr_score, match_method=ocr_method,
            match_ratio=1.0 if ocr_method != "unmatched" else 0.0,
            page_number=0,
            bbox=bbox or BoundingBox(x0=100, y0=100, x1=200, y1=120),
        )
    return f


def _doc() -> Document:
    return Document(
        id="d1",
        metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
        pages=[Page(page_number=0, width=612, height=792, text="x" * 100)],
        raw_text="x" * 100,
    )


def _result(fields: dict[str, ExtractedField]) -> ExtractionResult:
    return ExtractionResult(
        document_id="d1", schema_name="Invoice",
        data={k: f.value for k, f in fields.items()},
        fields=fields,
    )


def _llm(value, readable=True, usage=None):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=json.dumps({"value": value, "readable": readable}),
        model="gpt-4o",
        usage=usage or {},
    ))
    return llm


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (2550, 3300), "white")


class TestTriggerReason:
    def test_low_consensus_triggers(self):
        f = _field(100.0, consensus_ratio=0.33)
        assert "consensus" in _trigger_reason(f, VerificationPolicy())

    def test_high_consensus_no_trigger(self):
        f = _field(100.0, consensus_ratio=1.0)
        assert _trigger_reason(f, VerificationPolicy()) is None

    def test_low_ocr_score_triggers(self):
        f = _field(100.0, ocr_score=0.4)
        assert "OCR" in _trigger_reason(f, VerificationPolicy())

    def test_unmatched_triggers(self):
        f = _field(100.0, ocr_score=None, ocr_method="unmatched")
        assert "matched" in _trigger_reason(f, VerificationPolicy())

    def test_no_signals_no_trigger(self):
        f = _field(100.0)
        assert _trigger_reason(f, VerificationPolicy()) is None


class TestCropRegion:
    def test_crop_maps_points_to_pixels(self):
        img = _fake_image()  # 2550x3300 = 612x792 points at ~300 dpi
        page = Page(page_number=0, width=612, height=792)
        bbox = BoundingBox(x0=306, y0=396, x1=412, y1=420)
        cropped = _crop_region(img, bbox, page, padding=0.0)
        # 306pt of 612 = half the width -> 1275px
        assert abs(cropped.width - (412 - 306) / 612 * 2550) <= 2
        assert cropped.height < img.height

    def test_missing_page_dims_returns_full_image(self):
        img = _fake_image()
        page = Page(page_number=0)
        bbox = BoundingBox(x0=0, y0=0, x1=10, y1=10)
        assert _crop_region(img, bbox, page, 10.0) is img


class TestVerifyResult:
    async def test_agreeing_value_boosts_confidence(self):
        fields = {"total": _field(1234.56, ocr_score=0.4)}
        result = _result(fields)
        llm = _llm("1,234.56")  # normalizes equal

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            n = await verify_result(_doc(), result, Invoice, llm)

        assert n == 1
        v = result.fields["total"].verification
        assert v.verified and v.agrees and not v.changed
        assert result.fields["total"].trust_gate is True
        assert result.data["total"] == 1234.56  # unchanged

    async def test_differing_value_applied_with_audit(self):
        fields = {
            "supplier_name": _field("Acme Corp"),
            "total": _field(1234.56, ocr_score=0.4),
        }
        result = _result(fields)
        llm = _llm("7234.56")  # the zoom read a 7, not a 1

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(_doc(), result, Invoice, llm)

        f = result.fields["total"]
        assert f.verification.changed
        assert f.verification.original_value == 1234.56
        assert f.value == 7234.56
        assert result.data["total"] == 7234.56
        assert f.trust_gate is True

    async def test_schema_invalid_correction_not_applied(self):
        fields = {"total": _field(1234.56, ocr_score=0.4)}
        result = _result(fields)
        llm = _llm("not-a-number")

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(_doc(), result, Invoice, llm)

        f = result.fields["total"]
        assert f.value == 1234.56
        assert not f.verification.changed

    async def test_apply_corrections_false_records_only(self):
        fields = {"total": _field(1234.56, ocr_score=0.4)}
        result = _result(fields)
        llm = _llm("7234.56")

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(
                _doc(), result, Invoice, llm,
                policy=VerificationPolicy(apply_corrections=False),
            )

        f = result.fields["total"]
        assert f.value == 1234.56
        assert not f.verification.agrees
        assert not f.verification.changed
        assert f.verification.verified_value == "7234.56"

    async def test_unreadable_region_recorded(self):
        fields = {"total": _field(1234.56, ocr_score=0.4)}
        result = _result(fields)
        llm = _llm(None, readable=False)

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(_doc(), result, Invoice, llm)

        v = result.fields["total"].verification
        assert v is not None and not v.verified
        assert result.fields["total"].value == 1234.56

    async def test_max_fields_cap(self):
        fields = {
            f"f{i}": _field(f"v{i}", ocr_score=0.3) for i in range(8)
        }

        class Wide(BaseModel):
            pass

        result = _result(fields)
        llm = _llm("anything")

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(
                _doc(), result, Wide, llm,
                policy=VerificationPolicy(max_fields=3),
            )

        assert llm.complete.call_count == 3

    async def test_usage_merged_into_result(self):
        fields = {"total": _field(1234.56, ocr_score=0.4)}
        result = _result(fields)
        result.usage = TokenUsage(
            prompt_tokens=500, completion_tokens=100,
            total_tokens=600, n_llm_calls=1,
        )
        llm = _llm("1,234.56", usage={
            "prompt_tokens": 800, "completion_tokens": 20, "total_tokens": 820,
        })

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            await verify_result(_doc(), result, Invoice, llm)

        assert result.usage.n_llm_calls == 2
        assert result.usage.total_tokens == 1420

    async def test_no_weak_fields_no_calls(self):
        fields = {"total": _field(1234.56, consensus_ratio=1.0, ocr_score=0.95)}
        result = _result(fields)
        llm = _llm("x")

        n = await verify_result(_doc(), result, Invoice, llm)
        assert n == 0
        assert not llm.complete.called


class TestPipelineWiring:
    def test_pipeline_accepts_verification(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            verification={"trigger_ocr_below": 0.7, "max_fields": 3},
        )
        assert pipeline._verification["max_fields"] == 3

    def test_workflow_config_accepts_verification(self):
        from docuflow.workflow_config import load_workflow_config

        cfg = load_workflow_config({
            "name": "claims",
            "schema": {"total": {"type": "float"}},
            "verification": {"trigger_consensus_below": 0.8},
        })
        pipeline = cfg.build_pipeline()
        assert pipeline._verification == {"trigger_consensus_below": 0.8}

    async def test_verify_step_in_pipeline_state(self):
        from docuflow.workflow.state import PipelineState
        from docuflow.workflow.steps import VerifyFields

        state = PipelineState()
        state.document = _doc()
        state.extraction_result = _result(
            {"total": _field(1234.56, ocr_score=0.4)}
        )
        state.metadata["schema"] = Invoice

        llm = _llm("1,234.56")
        step = VerifyFields(llm=llm, policy=VerificationPolicy())

        with patch(
            "docuflow.rendering.renderer.render_page",
            new=AsyncMock(return_value=_fake_image()),
        ):
            state = await step.execute(state)

        assert state.extraction_result.fields["total"].verification is not None
        events = [e.event_type for e in state.trace.events]
        assert "verify_fields" in events
