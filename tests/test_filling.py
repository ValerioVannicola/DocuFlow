from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from docuflow.documents.models import BoundingBox, Document, DocumentMetadata
from docuflow.filling.api import fill_pdf_form
from docuflow.filling.detector import detect_blank_field_map
from docuflow.filling.llm_detector import detect_blank_field_map_llm
from docuflow.filling.models import FieldPlacement, FillingResult, FormField
from docuflow.filling.planner import build_acroform_plan, build_overlay_plan
from docuflow.workflow.state import PipelineState
from docuflow.workflow.steps import FillForm


class ClaimData(BaseModel):
    claimant_name: str = Field(alias="claimant.name")
    policy_number: str
    accepted_terms: bool = False
    optional_note: str | None = None


class FakeLLM:
    model = "fake-vision"

    def __init__(self, content: str):
        self.content = content
        self.messages: list[dict] = []

    async def complete(self, messages: list[dict], **kwargs: Any):
        from docuflow.extraction.llm.base import LLMResponse

        self.messages = messages
        return LLMResponse(
            content=self.content,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            model=self.model,
        )


def _touch_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")


def _make_static_blank_pdf(path: Path) -> None:
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")

    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.drawString(72, 720, "Name:")
    c.line(120, 718, 280, 718)
    c.save()


def test_acroform_plan_matches_alias_and_formats_checkbox() -> None:
    data = ClaimData(
        **{
            "claimant.name": "Mario Rossi",
            "policy_number": "POL-123",
            "accepted_terms": True,
        }
    )
    pdf_fields = [
        FormField(name="claimant.name", field_type="text", page_number=0),
        FormField(
            name="accepted_terms",
            field_type="checkbox",
            page_number=0,
            options=["On"],
        ),
    ]

    plan = build_acroform_plan(pdf_fields=pdf_fields, data=data)

    assert plan.assignments["claimant.name"] == "Mario Rossi"
    assert plan.assignments["accepted_terms"] == "On"
    assert plan.fields["claimant_name"].method == "exact_alias"
    assert plan.unmapped_model_fields == ["policy_number"]


def test_overlay_plan_uses_manual_field_map_coordinates() -> None:
    data = {"name": "Mario Rossi"}
    bbox = BoundingBox(x0=72, y0=120, x1=220, y1=138)

    plan = build_overlay_plan(
        data=data,
        field_map={"name": {"page_number": 0, "bbox": bbox.model_dump()}},
    )

    assert plan.placements["name"] == FieldPlacement(page_number=0, bbox=bbox)
    assert plan.fields["name"].formatted_value == "Mario Rossi"
    assert plan.fields["name"].bbox == bbox


def test_blank_detector_maps_labeled_static_blank(tmp_path) -> None:
    input_path = tmp_path / "static.pdf"
    _make_static_blank_pdf(input_path)

    field_map, warnings = detect_blank_field_map(input_path, {"name": "Mario Rossi"})

    assert "name" in field_map
    assert field_map["name"].page_number == 0
    assert field_map["name"].bbox.x0 <= 121
    assert any("opt-in" in warning for warning in warnings)


def test_overlay_does_not_auto_detect_blanks_by_default(tmp_path) -> None:
    input_path = tmp_path / "static.pdf"
    output_path = tmp_path / "static-filled.pdf"
    _make_static_blank_pdf(input_path)

    result = fill_pdf_form(
        str(input_path),
        {"name": "Mario Rossi"},
        output_path=str(output_path),
        strategy="overlay",
    )

    assert result.success is False
    assert result.fields == {}
    assert any("detect_blank_spaces=True" in warning for warning in result.warnings)


def test_overlay_can_opt_in_to_blank_detection(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "static.pdf"
    output_path = tmp_path / "static-filled.pdf"
    _make_static_blank_pdf(input_path)

    def fake_write(input_pdf: Path, output_pdf: Path, plan: Any, *, overflow: str = "shrink") -> list[str]:
        assert plan.fields["name"].method == "auto_detected_blank"
        output_pdf.write_bytes(input_pdf.read_bytes())
        return []

    monkeypatch.setattr("docuflow.filling.api.write_overlay", fake_write)

    result = fill_pdf_form(
        str(input_path),
        {"name": "Mario Rossi"},
        output_path=str(output_path),
        strategy="overlay",
        detect_blank_spaces=True,
    )

    assert result.success is True
    assert result.fields["name"].method == "auto_detected_blank"
    assert any("Automatic blank-space detection is opt-in" in warning for warning in result.warnings)


async def test_llm_blank_detector_converts_relative_bbox_to_page_points(monkeypatch, tmp_path) -> None:
    image_mod = pytest.importorskip("PIL.Image")
    input_path = tmp_path / "static.pdf"
    _touch_pdf(input_path)
    fake_image = image_mod.new("RGB", (200, 400), "white")
    fake_llm = FakeLLM(
        """
        {
          "placements": [
            {
              "field_name": "name",
              "page_number": 0,
              "bbox": {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.30},
              "label_text": "Name",
              "control_type": "text",
              "confidence": 0.91,
              "reason": "Blank line after Name label"
            }
          ],
          "warnings": []
        }
        """
    )

    async def fake_render_pages_encoded(path: str, dpi: int):
        assert dpi == 100
        buf = io.BytesIO()
        fake_image.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        # page dims in PDF points: 200px * 72/100 = 144pt wide, 400px * 72/100 = 288pt tall
        return [encoded], [(144.0, 288.0)]

    monkeypatch.setattr(
        "docuflow.filling.llm_detector._render_pages_encoded", fake_render_pages_encoded
    )

    field_map, warnings = await detect_blank_field_map_llm(
        input_path,
        {"name": "Mario Rossi"},
        llm=fake_llm,
        dpi=100,
    )

    placement = field_map["name"]
    assert placement.source == "llm"
    assert placement.label_text == "Name"
    assert placement.confidence == 0.91
    assert placement.bbox.x0 == pytest.approx(36.0)
    assert placement.bbox.y0 == pytest.approx(72.0)
    assert placement.bbox.x1 == pytest.approx(108.0)
    assert placement.bbox.y1 == pytest.approx(86.4)
    assert fake_llm.messages[1]["content"][1]["type"] == "image_url"
    assert any("LLM mapped 1/1" in warning for warning in warnings)


def test_overlay_can_use_llm_blank_detection(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "static.pdf"
    output_path = tmp_path / "static-filled.pdf"
    _touch_pdf(input_path)
    placement = FieldPlacement(
        page_number=0,
        bbox=BoundingBox(x0=72, y0=120, x1=220, y1=138),
        source="llm",
        confidence=0.88,
        label_text="Name",
    )

    async def fake_detect(*args: Any, **kwargs: Any):
        assert kwargs["model"] == "gemini/gemini-2.5-flash"
        return {"name": placement}, ["LLM blank-space detection is opt-in."]

    def fake_write(input_pdf: Path, output_pdf: Path, plan: Any, *, overflow: str = "shrink") -> list[str]:
        assert plan.fields["name"].method == "llm_detected_blank"
        output_pdf.write_bytes(input_pdf.read_bytes())
        return []

    monkeypatch.setattr("docuflow.filling.api.detect_blank_field_map_llm", fake_detect)
    monkeypatch.setattr("docuflow.filling.api.write_overlay", fake_write)

    result = fill_pdf_form(
        str(input_path),
        {"name": "Mario Rossi"},
        output_path=str(output_path),
        strategy="overlay",
        detect_blank_spaces=True,
        blank_detection_mode="llm",
    )

    assert result.success is True
    assert result.fields["name"].method == "llm_detected_blank"
    assert result.fields["name"].placement.confidence == 0.88


def test_fill_pdf_form_returns_filling_result_for_acroform(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "form.pdf"
    output_path = tmp_path / "filled.pdf"
    _touch_pdf(input_path)

    def fake_inspect(path: Path) -> list[FormField]:
        assert path == input_path
        return [FormField(name="policy_number", field_type="text", page_number=0)]

    def fake_write(
        input_pdf: Path,
        output_pdf: Path,
        assignments: dict[str, Any],
        *,
        flatten: bool = False,
    ) -> list[str]:
        assert assignments == {"policy_number": "POL-123"}
        output_pdf.write_bytes(input_pdf.read_bytes())
        return []

    monkeypatch.setattr("docuflow.filling.api.inspect_pdf_form", fake_inspect)
    monkeypatch.setattr("docuflow.filling.api.write_acroform", fake_write)

    result = fill_pdf_form(
        str(input_path),
        {"policy_number": "POL-123"},
        output_path=str(output_path),
    )

    assert isinstance(result, FillingResult)
    assert result.success is True
    assert result.strategy == "acroform"
    assert result.output_path == str(output_path)
    assert result.fields["policy_number"].target_name == "policy_number"


def test_fill_pdf_form_returns_filling_result_for_overlay(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "static.pdf"
    output_path = tmp_path / "static-filled.pdf"
    _touch_pdf(input_path)

    def fake_write(input_pdf: Path, output_pdf: Path, plan: Any, *, overflow: str = "shrink") -> list[str]:
        assert "name" in plan.placements
        output_pdf.write_bytes(input_pdf.read_bytes())
        return []

    monkeypatch.setattr("docuflow.filling.api.write_overlay", fake_write)

    result = fill_pdf_form(
        str(input_path),
        {"name": "Mario Rossi"},
        output_path=str(output_path),
        strategy="overlay",
        field_map={
            "name": {
                "page_number": 0,
                "bbox": {"x0": 72, "y0": 120, "x1": 220, "y1": 138},
            }
        },
    )

    assert result.success is True
    assert result.strategy == "overlay"
    assert result.fields["name"].method == "manual_overlay"


async def test_fill_form_workflow_step_stores_filling_result(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "form.pdf"
    _touch_pdf(input_path)
    document = Document(
        id="doc-1",
        metadata=DocumentMetadata(
            file_name="form.pdf",
            file_path=str(input_path),
            mime_type="application/pdf",
        ),
    )
    expected = FillingResult(
        input_path=str(input_path),
        document_id="doc-1",
        output_path=str(tmp_path / "filled.pdf"),
        strategy="acroform",
        success=True,
    )

    async def fake_fill_pdf_form_async(*args: Any, **kwargs: Any) -> FillingResult:
        assert kwargs["detect_blank_spaces"] is True
        assert kwargs["blank_detection_mode"] == "hybrid"
        return expected

    monkeypatch.setattr("docuflow.filling.api.fill_pdf_form_async", fake_fill_pdf_form_async)

    state = PipelineState(document=document)
    state = await FillForm(
        data={"name": "Mario"},
        detect_blank_spaces=True,
        blank_detection_mode="hybrid",
    ).execute(state)

    assert state.status == "pending"
    assert state.filling_result == expected


# --- Review / approval workflow -------------------------------------------------

_MANUAL_FIELD_MAP = {
    "name": {"page_number": 0, "bbox": {"x0": 72, "y0": 120, "x1": 220, "y1": 138}}
}


def _prepare_overlay_for_review(monkeypatch, tmp_path):
    from docuflow.filling.api import fill_pdf_form

    input_path = tmp_path / "static.pdf"
    output_path = tmp_path / "static-filled.pdf"
    _touch_pdf(input_path)

    calls: list[str] = []

    def fake_write(input_pdf: Path, output_pdf: Path, plan: Any, *, overflow: str = "shrink") -> list[str]:
        calls.append("write")
        output_pdf.write_bytes(input_pdf.read_bytes())
        return []

    monkeypatch.setattr("docuflow.filling.api.write_overlay", fake_write)

    result = fill_pdf_form(
        str(input_path),
        {"name": "Mario Rossi"},
        output_path=str(output_path),
        strategy="overlay",
        review=True,
        field_map=_MANUAL_FIELD_MAP,
    )
    return result, output_path, calls


def test_review_defers_write(monkeypatch, tmp_path) -> None:
    result, output_path, calls = _prepare_overlay_for_review(monkeypatch, tmp_path)

    assert calls == []  # nothing written during prepare
    assert output_path.exists() is False
    assert result.committed is False
    assert result.review_status == "pending"
    assert result.fields["name"].formatted_value == "Mario Rossi"


def test_edit_field_value_preserves_original_and_logs_correction(monkeypatch, tmp_path) -> None:
    result, _, _ = _prepare_overlay_for_review(monkeypatch, tmp_path)

    result.edit_field("name", value="Maria Bianchi", corrected_by="alice", reason="typo")

    field = result.fields["name"]
    assert field.value == "Maria Bianchi"
    assert field.formatted_value == "Maria Bianchi"
    assert field.original_value == "Mario Rossi"
    assert field.corrected is True
    assert result.data["name"] == "Maria Bianchi"
    assert len(result.corrections) == 1
    assert result.corrections[0].old_value == "Mario Rossi"
    assert result.corrections[0].corrected_by == "alice"


def test_edit_field_placement_moves_box(monkeypatch, tmp_path) -> None:
    from docuflow.documents.models import BoundingBox

    result, _, _ = _prepare_overlay_for_review(monkeypatch, tmp_path)

    new_box = BoundingBox(x0=100, y0=200, x1=300, y1=220)
    result.edit_field("name", bbox=new_box, page_number=1, corrected_by="alice")

    field = result.fields["name"]
    assert field.placement.bbox == new_box
    assert field.placement.page_number == 1
    assert field.bbox == new_box
    assert result.corrections[0].new_placement is not None
    assert result.corrections[0].new_placement.bbox == new_box


def test_approve_then_commit_writes(monkeypatch, tmp_path) -> None:
    from docuflow.filling.api import commit_fill

    result, output_path, calls = _prepare_overlay_for_review(monkeypatch, tmp_path)

    result.approve(approved_by="alice")
    assert result.review_status == "approved"

    committed = commit_fill(result)
    assert calls == ["write"]
    assert committed.committed is True
    assert output_path.exists() is True


def test_commit_without_approval_raises(monkeypatch, tmp_path) -> None:
    from docuflow.filling.api import commit_fill

    result, _, _ = _prepare_overlay_for_review(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="requires an approved result"):
        commit_fill(result)


def test_commit_with_force_writes_pending(monkeypatch, tmp_path) -> None:
    from docuflow.filling.api import commit_fill

    result, output_path, calls = _prepare_overlay_for_review(monkeypatch, tmp_path)

    commit_fill(result, force=True)
    assert calls == ["write"]
    assert output_path.exists() is True


def test_reject_blocks_commit(monkeypatch, tmp_path) -> None:
    from docuflow.filling.api import commit_fill

    result, _, calls = _prepare_overlay_for_review(monkeypatch, tmp_path)

    result.reject(rejected_by="alice", reason="wrong recipient")
    assert result.review_status == "rejected"

    with pytest.raises(ValueError, match="rejected"):
        commit_fill(result)
    assert calls == []


def test_double_approve_raises(monkeypatch, tmp_path) -> None:
    result, _, _ = _prepare_overlay_for_review(monkeypatch, tmp_path)
    result.approve()
    with pytest.raises(ValueError, match="already"):
        result.approve()


def test_edit_after_commit_raises(monkeypatch, tmp_path) -> None:
    from docuflow.filling.api import commit_fill

    result, _, _ = _prepare_overlay_for_review(monkeypatch, tmp_path)
    result.approve()
    commit_fill(result)
    with pytest.raises(ValueError, match="committed"):
        result.edit_field("name", value="X")


def test_review_rules_flag_auto_detected_and_low_confidence() -> None:
    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField, FillingResult
    from docuflow.filling.review import evaluate_fill_review

    result = FillingResult(input_path="x.pdf", strategy="overlay")
    result.fields = {
        "name": FilledField(
            field_name="name",
            placement=FieldPlacement(
                bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10), source="llm", confidence=0.3
            ),
            method="llm_detected_blank",
        )
    }
    result.unmapped_model_fields = ["policy_number"]

    reasons = evaluate_fill_review(result)
    assert any("confidence" in r for r in reasons)
    assert any("automatic blank detection" in r for r in reasons)
    assert any("policy_number" in r for r in reasons)


def test_preview_fill_renders_one_image_per_page(monkeypatch, tmp_path) -> None:
    image_mod = pytest.importorskip("PIL.Image")
    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField, FillingResult
    from docuflow.filling.preview import preview_fill

    input_path = tmp_path / "static.pdf"
    _touch_pdf(input_path)
    result = FillingResult(input_path=str(input_path), strategy="overlay")
    result.fields = {
        "name": FilledField(
            field_name="name",
            formatted_value="Mario Rossi",
            placement=FieldPlacement(
                page_number=0, bbox=BoundingBox(x0=72, y0=120, x1=220, y1=138)
            ),
            page_number=0,
            bbox=BoundingBox(x0=72, y0=120, x1=220, y1=138),
        )
    }

    async def fake_render_page(path: str, page_number: int = 0, dpi: int = 150):
        return image_mod.new("RGB", (600, 800), "white")

    monkeypatch.setattr("docuflow.rendering.renderer.render_page", fake_render_page)

    saved = preview_fill(result, output_dir=str(tmp_path), dpi=100)
    assert len(saved) == 1
    assert Path(saved[0]).exists()


async def test_store_round_trips_pending_fill(tmp_path) -> None:
    from docuflow.filling.models import FilledField, FillingResult
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(base_path=str(tmp_path / "store"))
    result = FillingResult(
        input_path="x.pdf",
        document_id="doc-9",
        strategy="overlay",
        needs_review=True,
        review_status="pending",
        fields={"name": FilledField(field_name="name", formatted_value="Mario")},
    )
    await store.save_filling_result(result)

    pending = await store.get_pending_fills()
    assert "doc-9" in pending

    loaded = await store.load_filling_result("doc-9")
    assert loaded is not None
    assert loaded.review_status == "pending"
    assert loaded.fields["name"].formatted_value == "Mario"


# ---------------------------------------------------------------------------
# Overflow page tests
# ---------------------------------------------------------------------------

def _make_single_page_pdf(path: Path, page_width: float = 200, page_height: float = 100) -> None:
    """Minimal single-page PDF via reportlab."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    c = rl_canvas.Canvas(str(path), pagesize=(page_width, page_height))
    c.showPage()
    c.save()


def test_wrap_text_splits_on_word_boundaries() -> None:
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:
        pytest.skip("reportlab not installed")

    from docuflow.filling.writer import _wrap_text

    lines = _wrap_text("one two three four five", "Helvetica", 10, 50)
    assert all(pdfmetrics.stringWidth(line, "Helvetica", 10) <= 50 for line in lines)
    assert " ".join(lines) == "one two three four five"
    assert len(lines) >= 1
    assert all(isinstance(ln, str) for ln in lines)


def test_wrap_text_respects_explicit_newlines() -> None:
    from docuflow.filling.writer import _wrap_text

    lines = _wrap_text("line one\nline two", "Helvetica", 10, 500)
    assert len(lines) == 2
    assert lines[0] == "line one"
    assert lines[1] == "line two"


def test_draw_wrapped_clips_and_warns_by_default(tmp_path) -> None:
    """overflow='wrap' clips lines that don't fit and records a warning."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    import io

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField
    from docuflow.filling.writer import _draw_wrapped

    placement = FieldPlacement(
        bbox=BoundingBox(x0=0, y0=0, x1=200, y1=30),  # only ~2 lines at 10pt
        font_size=10,
        multiline=True,
    )
    filled_field = FilledField(field_name="notes")
    long_text = " ".join([f"word{i}" for i in range(50)])

    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(200, 100))
    remaining = _draw_wrapped(
        c, long_text, placement, 100, filled_field,
        field_name="notes", overflow="wrap",
    )
    assert len(remaining) > 0
    assert any("clipped" in w for w in filled_field.warnings)


def test_draw_wrapped_returns_overflow_lines_for_page_policy(tmp_path) -> None:
    """overflow='page' returns overflow lines without issuing a warning."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    import io

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField
    from docuflow.filling.writer import _draw_wrapped

    placement = FieldPlacement(
        bbox=BoundingBox(x0=0, y0=0, x1=200, y1=30),
        font_size=10,
        multiline=True,
    )
    filled_field = FilledField(field_name="notes")
    long_text = " ".join([f"word{i}" for i in range(50)])

    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(200, 100))
    remaining = _draw_wrapped(
        c, long_text, placement, 100, filled_field,
        field_name="notes", overflow="page",
    )
    # overflow='page': lines returned, no clipping warning on the field
    assert len(remaining) > 0
    assert not any("clipped" in w for w in filled_field.warnings)


def test_draw_wrapped_raises_on_overflow_error_policy() -> None:
    """overflow='error' raises ValueError when content doesn't fit."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    import io

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField
    from docuflow.filling.writer import _draw_wrapped

    placement = FieldPlacement(
        bbox=BoundingBox(x0=0, y0=0, x1=200, y1=20),
        font_size=10,
        multiline=True,
    )
    long_text = " ".join([f"word{i}" for i in range(50)])
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(200, 100))
    with pytest.raises(ValueError, match="notes"):
        _draw_wrapped(
            c, long_text, placement, 100, FilledField(field_name="notes"),
            field_name="notes", overflow="error",
        )


def test_write_overlay_appends_pages_on_overflow(tmp_path) -> None:
    """overflow='page': the output PDF has more pages than the input."""
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf not installed")

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField, FillPlan
    from docuflow.filling.writer import write_overlay

    src = tmp_path / "src.pdf"
    dst = tmp_path / "dst.pdf"
    _make_single_page_pdf(src, page_width=200, page_height=100)

    # Very small bbox so the long text must overflow.
    placement = FieldPlacement(
        bbox=BoundingBox(x0=10, y0=10, x1=190, y1=40),
        font_size=10,
        multiline=True,
    )
    long_value = " ".join([f"word{i}" for i in range(80)])
    filled_field = FilledField(
        field_name="notes", value=long_value, formatted_value=long_value
    )
    plan = FillPlan(
        strategy="overlay",
        fields={"notes": filled_field},
        placements={"notes": placement},
    )

    write_overlay(src, dst, plan, overflow="page")

    reader = PdfReader(str(dst))
    assert reader.get_num_pages() > 1, "Expected continuation pages to be appended"
    assert any("appended" in w for w in filled_field.warnings)


def test_draw_continuation_page_always_makes_progress() -> None:
    """A continuation page too short for even one line must still consume a line.

    Otherwise the same line list is returned unchanged and write_overlay's
    ``while remaining_lines:`` loop appends pages forever.
    """
    pytest.importorskip("reportlab")

    from reportlab.pdfgen import canvas as canvas_mod

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField
    from docuflow.filling.writer import _draw_continuation_page

    placement = FieldPlacement(
        bbox=BoundingBox(x0=10, y0=10, x1=190, y1=40),
        font_size=10,
        multiline=True,
    )
    filled_field = FilledField(field_name="notes", value="x", formatted_value="x")
    lines = ["line one", "line two", "line three"]

    # page_height far smaller than the top margin (font_size * 2) so y < y_min
    # for the very first line — the unguarded version would return lines unchanged.
    canvas = canvas_mod.Canvas(io.BytesIO(), pagesize=(200, 5))
    remaining = _draw_continuation_page(
        canvas, lines, placement, 5, filled_field, field_name="notes"
    )

    assert len(remaining) < len(lines), "Continuation page must consume at least one line"


def test_write_overlay_terminates_with_oversized_lines(tmp_path) -> None:
    """overflow='page' on a page too short for a single wrapped line must finish."""
    pytest.importorskip("pypdf")

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField, FillPlan
    from docuflow.filling.writer import write_overlay

    src = tmp_path / "src.pdf"
    dst = tmp_path / "dst.pdf"
    # Extremely short page: continuation pages cannot fit a full line either.
    _make_single_page_pdf(src, page_width=200, page_height=30)

    placement = FieldPlacement(
        bbox=BoundingBox(x0=10, y0=5, x1=190, y1=25),
        font_size=10,
        multiline=True,
    )
    long_value = " ".join([f"word{i}" for i in range(40)])
    filled_field = FilledField(
        field_name="notes", value=long_value, formatted_value=long_value
    )
    plan = FillPlan(
        strategy="overlay",
        fields={"notes": filled_field},
        placements={"notes": placement},
    )

    # Must return rather than loop forever appending pages.
    write_overlay(src, dst, plan, overflow="page")

    from pypdf import PdfReader

    reader = PdfReader(str(dst))
    assert reader.get_num_pages() >= 2


def test_write_overlay_raises_on_single_line_error_overflow(tmp_path) -> None:
    """overflow='error' must also protect non-multiline placements."""
    pytest.importorskip("pypdf")

    from docuflow.documents.models import BoundingBox
    from docuflow.filling.models import FieldPlacement, FilledField, FillPlan
    from docuflow.filling.writer import write_overlay

    src = tmp_path / "src.pdf"
    dst = tmp_path / "dst.pdf"
    _make_single_page_pdf(src, page_width=200, page_height=100)

    long_value = "This value is intentionally too long for the target box"
    plan = FillPlan(
        strategy="overlay",
        fields={
            "name": FilledField(
                field_name="name",
                value=long_value,
                formatted_value=long_value,
            )
        },
        placements={
            "name": FieldPlacement(
                bbox=BoundingBox(x0=10, y0=10, x1=40, y1=24),
                font_size=10,
            )
        },
    )

    with pytest.raises(ValueError, match="name"):
        write_overlay(src, dst, plan, overflow="error")
