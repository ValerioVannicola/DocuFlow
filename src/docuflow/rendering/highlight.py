"""Render PDF pages with field evidence highlighted and save to disk."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from docuflow._sync import run_sync

if TYPE_CHECKING:
    from docuflow.extraction.models import ExtractionResult

# Default semi-transparent yellow
DEFAULT_COLOR: tuple[int, int, int, int] = (255, 220, 0, 90)

# Cycling palette used when color="auto" (distinct color per field)
_PALETTE: list[tuple[int, int, int, int]] = [
    (255, 220, 0, 90),    # yellow
    (80, 160, 255, 90),   # blue
    (80, 220, 120, 90),   # green
    (255, 80, 80, 90),    # red
    (200, 80, 255, 90),   # purple
    (255, 140, 0, 90),    # orange
    (0, 200, 220, 90),    # cyan
    (255, 80, 180, 90),   # pink
]


def _resolve_color(
    color: str | tuple | None,
    field_index: int,
) -> tuple[int, int, int, int]:
    """Return an RGBA tuple for the given color spec."""
    if color == "auto":
        return _PALETTE[field_index % len(_PALETTE)]
    if color is None:
        return DEFAULT_COLOR
    if isinstance(color, tuple):
        r, g, b = color[:3]
        a = color[3] if len(color) == 4 else 90
        return (int(r), int(g), int(b), int(a))
    # Named CSS color strings via PIL
    from PIL import ImageColor
    r, g, b = ImageColor.getrgb(color)
    return (r, g, b, 90)


def _collect_rects(
    result: ExtractionResult,
    fields: list[str] | None,
    color: str | tuple | None,
) -> dict[int, list[tuple[str, object, tuple[int, int, int, int]]]]:
    selected = fields or list(result.fields.keys())
    by_page: dict[int, list] = {}
    for idx, name in enumerate(selected):
        field = result.fields.get(name)
        if field is None:
            continue
        c = _resolve_color(color, idx)
        boxes: list[tuple[int, object]] = []
        for ev in field.evidence:
            if ev.rects:
                for rect in ev.rects:
                    if rect.bbox is not None:
                        boxes.append((rect.page_number, rect.bbox))
            elif ev.bbox is not None:
                boxes.append((ev.page_number, ev.bbox))
        if field.ocr is not None:
            if field.ocr.rects:
                for rect in field.ocr.rects:
                    if rect.bbox is not None:
                        boxes.append((rect.page_number, rect.bbox))
            elif field.ocr.bbox is not None and field.ocr.page_number is not None:
                boxes.append((field.ocr.page_number, field.ocr.bbox))
        for page_num, bbox in boxes:
            by_page.setdefault(page_num, []).append((name, bbox, c))
    return by_page


def _darken(color: tuple[int, int, int, int], factor: float = 0.55) -> tuple[int, int, int, int]:
    """Return the same hue at reduced brightness, fully opaque."""
    r, g, b, _ = color
    return (int(r * factor), int(g * factor), int(b * factor), 255)


def _annotate(img: object, boxes: list, dpi: int, show_labels: bool = True) -> object:
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

    scale = dpi / 72.0
    overlay = PILImage.new("RGBA", img.size, (0, 0, 0, 0))  # type: ignore[arg-type]
    draw = ImageDraw.Draw(overlay)
    if show_labels:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(11, dpi // 12))
        except Exception:
            font = ImageFont.load_default()

    for field_name, bbox, color in boxes:
        x0 = round(bbox.x0 * scale)
        y0 = round(bbox.y0 * scale)
        x1 = round(bbox.x1 * scale)
        y1 = round(bbox.y1 * scale)
        w, h = img.size  # type: ignore[attr-defined]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        border = _darken(color)
        draw.rectangle([x0, y0, x1, y1], fill=color, outline=border, width=2)
        if show_labels:
            label_y = y0 - max(14, dpi // 10) if y0 > max(14, dpi // 10) else y1
            draw.text((x0 + 2, label_y), field_name.replace("_", " "), fill=border, font=font)

    return PILImage.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")  # type: ignore[union-attr]


async def highlight_fields_async(
    file_path: str,
    result: ExtractionResult,
    output_dir: str | Path = ".",
    fields: list[str] | None = None,
    dpi: int = 150,
    format: str = "png",
    color: str | tuple | None = None,
    show_labels: bool = True,
) -> list[str]:
    """Render each page that has field evidence, draw colored bounding boxes, save to disk.

    Returns a list of saved file paths (one per page with evidence).

    Args:
        file_path: Path to the source PDF.
        result: Extraction result whose field evidence provides bounding boxes.
        output_dir: Directory to save annotated images. Created if absent.
        fields: Field names to highlight. None highlights every field.
        dpi: Render resolution (150 = readable, 72 = fast).
        format: Output image format ("png" or "jpeg").
        color: Highlight color. Accepts:
            - None (default): semi-transparent yellow for all fields
            - A CSS color name string: ``"red"``, ``"cyan"``, ``"#ff0"``
            - An RGB/RGBA tuple: ``(255, 0, 0)`` or ``(255, 0, 0, 120)``
            - ``"auto"``: a distinct color per field from the built-in palette
        show_labels: Draw the field name above each box. Default True.
    """
    from docuflow.rendering.renderer import render_page

    by_page = _collect_rects(result, fields, color)
    if not by_page:
        return []

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem
    saved: list[str] = []

    for page_num, boxes in sorted(by_page.items()):
        img = await render_page(file_path, page_num, dpi=dpi)
        annotated = _annotate(img, boxes, dpi, show_labels=show_labels)
        dest = out / f"{stem}_page_{page_num}_highlighted.{format}"
        annotated.save(str(dest), format=format.upper())
        saved.append(str(dest))

    return saved


def highlight_fields(
    file_path: str,
    result: ExtractionResult,
    output_dir: str | Path = ".",
    fields: list[str] | None = None,
    dpi: int = 150,
    format: str = "png",
    color: str | tuple | None = None,
    show_labels: bool = True,
) -> list[str]:
    """Sync version of :func:`highlight_fields_async`. Returns saved file paths.

    Args:
        file_path: Path to the source PDF.
        result: Extraction result whose field evidence provides bounding boxes.
        output_dir: Directory to save annotated images. Created if absent.
        fields: Field names to highlight. None highlights every field.
        dpi: Render resolution (150 = readable, 72 = fast).
        format: Output image format ("png" or "jpeg").
        color: Highlight color — None (yellow), CSS name, RGB/RGBA tuple, or ``"auto"``.
        show_labels: Draw the field name above each box. Default True.
    """
    return run_sync(
        highlight_fields_async(
            file_path, result,
            output_dir=output_dir, fields=fields,
            dpi=dpi, format=format, color=color, show_labels=show_labels,
        )
    )
