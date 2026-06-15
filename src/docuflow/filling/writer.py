from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path
from typing import Any

from docuflow.filling.models import FieldPlacement, FillPlan, OverflowPolicy


def write_acroform(
    input_path: str | Path,
    output_path: str | Path,
    assignments: dict[str, Any],
    *,
    flatten: bool = False,
) -> list[str]:
    """Write values into existing PDF AcroForm fields."""
    pdf_reader_cls, pdf_writer_cls = _require_pypdf()
    reader = pdf_reader_cls(str(input_path))
    writer = pdf_writer_cls()
    writer.clone_document_from_reader(reader)

    warnings: list[str] = []
    _set_need_appearances(writer)

    unsupported_flatten = flatten
    for page in writer.pages:
        try:
            writer.update_page_form_field_values(
                page,
                assignments,
                auto_regenerate=True,
                flatten=flatten,
            )
            unsupported_flatten = False
        except TypeError:
            writer.update_page_form_field_values(
                page,
                assignments,
                auto_regenerate=True,
            )

    if unsupported_flatten:
        warnings.append(
            "The installed pypdf version does not support flatten=True; "
            "the output PDF remains editable."
        )

    with Path(output_path).open("wb") as file:
        writer.write(file)
    return warnings


def write_overlay(
    input_path: str | Path,
    output_path: str | Path,
    plan: FillPlan,
    *,
    overflow: OverflowPolicy = "shrink",
) -> list[str]:
    """Overlay values at explicit placements on a static PDF."""
    pdf_reader_cls, pdf_writer_cls = _require_pypdf()
    canvas_cls = _require_reportlab_canvas()

    reader = pdf_reader_cls(str(input_path))
    writer = pdf_writer_cls()
    warnings: list[str] = []

    by_page: dict[int, list[tuple[str, FieldPlacement]]] = defaultdict(list)
    for field_name, placement in plan.placements.items():
        by_page[placement.page_number].append((field_name, placement))

    for page_number, page in enumerate(reader.pages):
        page_width = float(page.mediabox.right) - float(page.mediabox.left)
        page_height = float(page.mediabox.top) - float(page.mediabox.bottom)
        overlay_fields = by_page.get(page_number, [])
        if overlay_fields:
            packet = io.BytesIO()
            canvas = canvas_cls(packet, pagesize=(page_width, page_height))
            for field_name, placement in overlay_fields:
                value = str(plan.fields[field_name].formatted_value)
                font_size = _fit_font_size(value, placement, overflow=overflow)
                if font_size != placement.font_size:
                    plan.fields[field_name].warnings.append(
                        f"Font size shrunk from {placement.font_size} to {font_size}."
                    )
                canvas.setFont(placement.font_name, font_size)
                x, y = _text_origin(placement, page_height, value, font_size)
                canvas.drawString(x, y, value)
            canvas.save()
            packet.seek(0)
            overlay_pdf = pdf_reader_cls(packet)
            page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)

    if not by_page:
        warnings.append("No overlay placements were available; output PDF was not modified.")

    with Path(output_path).open("wb") as file:
        writer.write(file)
    return warnings


def _require_pypdf() -> tuple[Any, Any]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise ImportError(
            "PDF form filling requires pypdf. Install it with: "
            "pip install 'docuflow[forms]'"
        ) from exc
    return PdfReader, PdfWriter


def _require_reportlab_canvas() -> Any:
    try:
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise ImportError(
            "Static PDF overlay filling requires reportlab. Install it with: "
            "pip install 'docuflow[forms]'"
        ) from exc
    return Canvas


def _set_need_appearances(writer: Any) -> None:
    try:
        writer.set_need_appearances_writer(True)
    except AttributeError:
        return


def _fit_font_size(
    value: str,
    placement: FieldPlacement,
    *,
    overflow: OverflowPolicy,
) -> float:
    if not value or overflow != "shrink":
        return placement.font_size
    # Conservative approximation: average Helvetica character width ~0.5em.
    estimated_width = len(value) * placement.font_size * 0.5
    if estimated_width <= placement.bbox.width:
        return placement.font_size
    return max(6.0, placement.font_size * placement.bbox.width / estimated_width)


def _text_origin(
    placement: FieldPlacement,
    page_height: float,
    value: str,
    font_size: float,
) -> tuple[float, float]:
    x = placement.bbox.x0
    if placement.align != "left":
        estimated_width = len(value) * font_size * 0.5
        if placement.align == "center":
            x = placement.bbox.x0 + max(0.0, placement.bbox.width - estimated_width) / 2
        else:
            x = placement.bbox.x1 - estimated_width
    # ReportLab uses bottom-left origin. Place text just above the field bottom.
    y = page_height - placement.bbox.y1 + max(1.0, (placement.bbox.height - font_size) / 2)
    return x, y
