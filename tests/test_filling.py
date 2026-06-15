from __future__ import annotations

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

    async def fake_render_all_pages(path: str, dpi: int):
        assert dpi == 100
        return [fake_image]

    monkeypatch.setattr("docuflow.rendering.renderer.render_all_pages", fake_render_all_pages)

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
        assert kwargs["model"] == "openai/gpt-4o"
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
