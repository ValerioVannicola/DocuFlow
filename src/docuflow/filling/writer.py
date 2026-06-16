from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path
from typing import Any

from docuflow.filling.models import FieldPlacement, FilledField, FillPlan, OverflowPolicy


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
                page, assignments, auto_regenerate=True, flatten=flatten,
            )
            unsupported_flatten = False
        except TypeError:
            try:
                writer.update_page_form_field_values(page, assignments, auto_regenerate=True)
            except TypeError:
                writer.update_page_form_field_values(page, assignments)

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

    # page_sizes[i] is (width, height) of page i — needed when appending overflow pages.
    page_sizes: list[tuple[float, float]] = []

    # Pending overflow: list of (page_size, placement, remaining_lines, filled_field, field_name)
    overflow_pending_type = tuple[tuple[float, float], FieldPlacement, list[str], FilledField, str]
    pending_overflow: list[overflow_pending_type] = []

    for page_number, page in enumerate(reader.pages):
        page_width = float(page.mediabox.right) - float(page.mediabox.left)
        page_height = float(page.mediabox.top) - float(page.mediabox.bottom)
        page_sizes.append((page_width, page_height))
        overlay_fields = by_page.get(page_number, [])
        # Attach the page to the writer before merging. Merging onto a page that
        # is not yet owned by a writer is deprecated in pypdf and removed in v7.
        writer.add_page(page)
        if overlay_fields:
            packet = io.BytesIO()
            canvas = canvas_cls(packet, pagesize=(page_width, page_height))
            for field_name, placement in overlay_fields:
                value = str(plan.fields[field_name].formatted_value)
                if placement.multiline or overflow in ("wrap", "page"):
                    remaining = _draw_wrapped(
                        canvas, value, placement, page_height,
                        plan.fields[field_name], field_name=field_name, overflow=overflow,
                    )
                    if remaining and overflow == "page":
                        pending_overflow.append((
                            (page_width, page_height),
                            placement,
                            remaining,
                            plan.fields[field_name],
                            field_name,
                        ))
                else:
                    if overflow == "error" and _text_width(value, placement) > placement.bbox.width:
                        raise ValueError(
                            f"Field '{field_name}': text does not fit in the bounding box."
                        )
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
            writer.pages[-1].merge_page(overlay_pdf.pages[0])

    if not by_page:
        warnings.append("No overlay placements were available; output PDF was not modified.")

    # Append continuation pages for fields whose content overflowed.
    for page_size, placement, remaining_lines, filled_field, field_name in pending_overflow:
        page_num_start = writer.get_num_pages() + 1
        continuation = 0
        while remaining_lines:
            pw, ph = page_size
            packet = io.BytesIO()
            canvas = canvas_cls(packet, pagesize=(pw, ph))
            remaining_lines = _draw_continuation_page(
                canvas, remaining_lines, placement, ph,
                filled_field, field_name=field_name,
            )
            canvas.save()
            packet.seek(0)
            cont_pdf = pdf_reader_cls(packet)
            writer.add_page(cont_pdf.pages[0])
            continuation += 1
        page_num_end = page_num_start + continuation - 1
        page_range = (
            f"page {page_num_start}"
            if page_num_start == page_num_end
            else f"pages {page_num_start}-{page_num_end}"
        )
        filled_field.warnings.append(
            f"Content overflowed; continued on appended {page_range}."
        )

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
        # pypdf 5+: the method was removed; write directly into the AcroForm dict
        try:
            from pypdf.generic import BooleanObject, NameObject
            acroform = writer._root_object.get("/AcroForm")
            if acroform is not None:
                acroform.update({NameObject("/NeedAppearances"): BooleanObject(True)})
        except Exception:
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


def _text_width(value: str, placement: FieldPlacement) -> float:
    try:
        from reportlab.pdfbase import pdfmetrics

        return float(pdfmetrics.stringWidth(value, placement.font_name, placement.font_size))
    except ImportError:
        return len(value) * placement.font_size * 0.5


def _wrap_text(value: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """Word-wrap value into lines no wider than max_width. Respects explicit newlines."""
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:
        return [value]

    lines: list[str] = []
    for para in (value.splitlines() or [""]):
        words = para.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_wrapped(
    canvas: Any,
    value: str,
    placement: FieldPlacement,
    page_height: float,
    filled_field: FilledField,
    *,
    field_name: str,
    overflow: OverflowPolicy,
) -> list[str]:
    """Draw word-wrapped text inside placement bbox. Returns lines that did not fit."""
    font_name = placement.font_name
    font_size = placement.font_size
    line_height = font_size * 1.2

    lines = _wrap_text(value, font_name, font_size, placement.bbox.width)

    # ReportLab origin is bottom-left; bbox.y0 = top edge, bbox.y1 = bottom edge.
    y_top = page_height - placement.bbox.y0 - font_size
    y_min = page_height - placement.bbox.y1

    canvas.setFont(font_name, font_size)
    overflow_lines: list[str] = []
    for i, line in enumerate(lines):
        y = y_top - i * line_height
        if y < y_min:
            overflow_lines = lines[i:]
            break
        canvas.drawString(placement.bbox.x0, y, line)

    if overflow_lines:
        if overflow == "error":
            raise ValueError(
                f"Field '{field_name}': {len(overflow_lines)} wrapped line(s) did not fit."
            )
        if overflow != "page":
            filled_field.warnings.append(
                f"{len(overflow_lines)} wrapped line(s) did not fit in the bounding box "
                "and were clipped."
            )

    return overflow_lines


def _draw_continuation_page(
    canvas: Any,
    lines: list[str],
    placement: FieldPlacement,
    page_height: float,
    filled_field: FilledField,
    *,
    field_name: str,
) -> list[str]:
    """Draw as many lines as fit starting at the top margin of a continuation page.

    Returns any lines that still didn't fit (caller appends another page).
    """
    font_name = placement.font_name
    font_size = placement.font_size
    line_height = font_size * 1.2
    top_margin = font_size * 2  # small top margin on continuation pages
    y_top = page_height - top_margin - font_size
    y_min = font_size  # bottom margin

    canvas.setFont(font_name, font_size)
    remaining: list[str] = []
    for i, line in enumerate(lines):
        y = y_top - i * line_height
        # Always render at least the first line, even if the page is too short
        # to hold it. Otherwise a single oversized line would be returned
        # unchanged and the caller's append-page loop would never terminate.
        if y < y_min and i > 0:
            remaining = lines[i:]
            break
        canvas.drawString(placement.bbox.x0, y, line)
    return remaining


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
