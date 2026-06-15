from __future__ import annotations

import base64
import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from docuflow.constants import DEFAULT_DPI
from docuflow.documents.models import BoundingBox
from docuflow.filling.models import FieldPlacement
from docuflow.filling.planner import collect_data_fields
from docuflow.observability.traces import Trace

JSON_MODE = {"type": "json_object"}

LLM_BLANK_DETECTION_SYSTEM_PROMPT = """You are a PDF form placement planner.

You receive page images of a PDF form and a list of fields that the caller wants to fill.
Your task is ONLY to locate where each field should be written. Do not invent or fill values.

Return JSON with this exact shape:
{
  "placements": [
    {
      "field_name": "one of the provided field names",
      "page_number": 0,
      "bbox": {"x0": 0.12, "y0": 0.34, "x1": 0.56, "y1": 0.38},
      "label_text": "nearby label or context",
      "control_type": "text",
      "confidence": 0.86,
      "reason": "why this blank belongs to the field"
    }
  ],
  "warnings": []
}

Coordinate contract:
- `page_number` is zero-based.
- `bbox` coordinates MUST be relative to the full page image, from 0.0 to 1.0.
- The origin is top-left: x grows right, y grows down.
- x0/y0 is the top-left corner of the write area; x1/y1 is the bottom-right corner.
- Use the blank area where text should be placed, not the label text.

Supported control types: text, textarea, checkbox, radio, date, signature, unknown.
Only return placements for the listed field names. If unsure, omit the field or use low confidence.
"""


class RelativeBBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class LLMPlacement(BaseModel):
    field_name: str
    page_number: int = 0
    bbox: RelativeBBox
    label_text: str = ""
    control_type: Literal[
        "text", "textarea", "checkbox", "radio", "date", "signature", "unknown"
    ] = "text"
    confidence: float = 0.0
    reason: str = ""


class LLMPlacementResponse(BaseModel):
    placements: list[LLMPlacement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def detect_blank_field_map_llm(
    path: str | Path,
    data: BaseModel | Mapping[str, Any],
    *,
    llm: Any = None,
    model: str = "gemini/gemini-2.5-flash",
    llm_kwargs: Mapping[str, Any] | None = None,
    dpi: int = DEFAULT_DPI,
    min_confidence: float = 0.5,
    skip_none: bool = True,
    trace: Trace | None = None,
) -> tuple[dict[str, FieldPlacement], list[str]]:
    """Use a vision LLM to locate static PDF form blanks.

    The LLM returns page-relative boxes. This function converts them into
    DocuFlow's standard page coordinates: top-left origin in PDF points.
    """
    data_fields = collect_data_fields(data, skip_none=skip_none)
    if not data_fields:
        return {}, ["No data fields were available for LLM blank detection."]

    llm = llm or _default_llm(model=model, llm_kwargs=llm_kwargs)

    # Render pages one at a time and encode to base64 immediately so we never
    # hold all PIL Images in memory simultaneously.
    images_base64, page_dims = await _render_pages_encoded(path, dpi=dpi)

    response = await llm.complete(
        _build_messages(data_fields, images_base64),
        temperature=0.0,
        response_format=JSON_MODE,
    )
    parsed = _parse_response(response.content)
    allowed_fields = {field.name for field in data_fields}
    placements: dict[str, FieldPlacement] = {}
    warnings = [
        "LLM blank-space detection is opt-in and heuristic; review the generated PDF before use."
    ]
    warnings.extend(parsed.warnings)

    for placement in parsed.placements:
        if placement.field_name not in allowed_fields:
            warnings.append(
                f"LLM returned unknown field '{placement.field_name}', so it was ignored."
            )
            continue
        if placement.confidence < min_confidence:
            warnings.append(
                f"LLM placement for '{placement.field_name}' below confidence threshold "
                f"({placement.confidence:.2f} < {min_confidence:.2f}), so it was ignored."
            )
            continue
        if placement.page_number < 0 or placement.page_number >= len(page_dims):
            warnings.append(
                f"LLM placement for '{placement.field_name}' has out-of-range page "
                f"{placement.page_number}, so it was ignored."
            )
            continue

        page_width, page_height = page_dims[placement.page_number]
        bbox = _relative_to_page_bbox(placement.bbox, page_width, page_height)
        if bbox.width <= 1 or bbox.height <= 1:
            warnings.append(
                f"LLM placement for '{placement.field_name}' is too small, so it was ignored."
            )
            continue

        placements[placement.field_name] = FieldPlacement(
            page_number=placement.page_number,
            bbox=bbox,
            multiline=placement.control_type == "textarea",
            source="llm",
            label_text=placement.label_text,
            confidence=placement.confidence,
            reason=placement.reason,
            control_type=placement.control_type,
        )

    warnings.append(
        f"LLM mapped {len(placements)}/{len(data_fields)} data field(s) to static blank spaces."
    )
    if trace:
        trace.add_event(
            "llm_blank_detection",
            step_name="fill_form",
            model=getattr(llm, "model", ""),
            detected_fields=len(placements),
            n_pages=len(page_dims),
            dpi=dpi,
            usage=getattr(response, "usage", {}),
        )
    return placements, warnings


async def _render_pages_encoded(
    path: str | Path,
    dpi: int,
) -> tuple[list[str], list[tuple[float, float]]]:
    """Render each PDF page, encode to base64, and return (encoded_list, page_dims_in_pts).

    Pages are encoded one at a time so we never hold all PIL Images simultaneously.
    """
    from docuflow.rendering.renderer import render_page

    page_count = _count_pages(path)
    images_base64: list[str] = []
    page_dims: list[tuple[float, float]] = []
    for page_num in range(page_count):
        img = await render_page(str(path), page_num, dpi=dpi)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        images_base64.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        page_dims.append((float(img.width) * 72.0 / dpi, float(img.height) * 72.0 / dpi))
    return images_base64, page_dims


def _count_pages(path: str | Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 1


def _default_llm(model: str, llm_kwargs: Mapping[str, Any] | None) -> Any:
    from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

    return LiteLLMAdapter(model=model, **dict(llm_kwargs or {}))


def _build_messages(data_fields: list[Any], images_base64: list[str]) -> list[dict]:
    field_lines = []
    for field in data_fields:
        aliases = ", ".join(alias for alias in field.aliases if alias != field.name)
        details = [f"name={field.name!r}"]
        if aliases:
            details.append(f"aliases={aliases!r}")
        if field.description:
            details.append(f"description={field.description!r}")
        field_lines.append("- " + "; ".join(details))

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Locate static PDF form blanks for these fields. "
                "Return only placements for these field names.\n\n"
                + "\n".join(field_lines)
            ),
        }
    ]
    for image in images_base64:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image}"},
            }
        )
    return [
        {"role": "system", "content": LLM_BLANK_DETECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _parse_response(content: str) -> LLMPlacementResponse:
    return LLMPlacementResponse.model_validate(json.loads(_strip_markdown_fences(content)))


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _relative_to_page_bbox(
    bbox: RelativeBBox,
    page_width: float,
    page_height: float,
) -> BoundingBox:
    x0 = _clamp(bbox.x0)
    y0 = _clamp(bbox.y0)
    x1 = _clamp(bbox.x1)
    y1 = _clamp(bbox.y1)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return BoundingBox(
        x0=x0 * page_width,
        y0=y0 * page_height,
        x1=x1 * page_width,
        y1=y1 * page_height,
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
