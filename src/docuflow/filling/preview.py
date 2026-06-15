"""Render a planned PDF fill to images so a reviewer (or UI) can see it before commit.

This is the backend a review UI would consume: it draws each planned value at its
target location on a rendered page image and saves PNGs. No PDF is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from docuflow._sync import run_sync

if TYPE_CHECKING:
    from docuflow.filling.models import FillingResult

# Semi-transparent green for "will be filled" + a darker border.
_FILL_COLOR: tuple[int, int, int, int] = (80, 200, 120, 80)
_NEEDS_REVIEW_COLOR: tuple[int, int, int, int] = (255, 170, 0, 90)


def _darken(color: tuple[int, int, int, int], factor: float = 0.5) -> tuple[int, int, int, int]:
    r, g, b, _ = color
    return (int(r * factor), int(g * factor), int(b * factor), 255)


def _collect(result: FillingResult) -> dict[int, list]:
    """Group placeable fields by page number."""
    by_page: dict[int, list] = {}
    for name, field in result.fields.items():
        bbox = field.placement.bbox if field.placement is not None else field.bbox
        page = field.placement.page_number if field.placement is not None else field.page_number
        if bbox is None or page is None:
            continue
        flagged = field.corrected or bool(field.warnings)
        by_page.setdefault(page, []).append(
            (name, bbox, str(field.formatted_value), flagged)
        )
    return by_page


def _annotate(img: object, boxes: list, dpi: int) -> object:
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

    scale = dpi / 72.0
    overlay = PILImage.new("RGBA", img.size, (0, 0, 0, 0))  # type: ignore[arg-type]
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(11, dpi // 12))
    except Exception:
        font = ImageFont.load_default()

    for field_name, bbox, value, flagged in boxes:
        color = _NEEDS_REVIEW_COLOR if flagged else _FILL_COLOR
        border = _darken(color)
        w, h = img.size  # type: ignore[attr-defined]
        x0, y0 = max(0, round(bbox.x0 * scale)), max(0, round(bbox.y0 * scale))
        x1, y1 = min(w, round(bbox.x1 * scale)), min(h, round(bbox.y1 * scale))
        if x1 <= x0 or y1 <= y0:
            continue
        draw.rectangle([x0, y0, x1, y1], fill=color, outline=border, width=2)
        if value:
            draw.text((x0 + 3, y0 + 2), value, fill=(0, 0, 0, 255), font=font)
        label_y = y0 - max(14, dpi // 10) if y0 > max(14, dpi // 10) else y1 + 2
        draw.text((x0 + 2, label_y), field_name.replace("_", " "), fill=border, font=font)

    return PILImage.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")  # type: ignore[union-attr]


async def preview_fill_async(
    result: FillingResult,
    output_dir: str | Path = ".",
    *,
    dpi: int = 150,
    format: str = "png",
) -> list[str]:
    """Render each page with planned values overlaid; save images. Returns saved paths.

    Fields edited by a reviewer or carrying warnings are highlighted in amber;
    clean placements are green. Fields without a known location (e.g. some
    AcroForm widgets) are skipped.
    """
    from docuflow.rendering.renderer import render_page

    by_page = _collect(result)
    if not by_page:
        return []

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(result.input_path).stem
    saved: list[str] = []
    for page_num, boxes in sorted(by_page.items()):
        img = await render_page(result.input_path, page_num, dpi=dpi)
        annotated = _annotate(img, boxes, dpi)
        dest = out / f"{stem}_page_{page_num}_fill_preview.{format}"
        annotated.save(str(dest), format=format.upper())
        saved.append(str(dest))
    return saved


def preview_fill(
    result: FillingResult,
    output_dir: str | Path = ".",
    *,
    dpi: int = 150,
    format: str = "png",
) -> list[str]:
    """Sync version of :func:`preview_fill_async`. Returns saved image paths."""
    return run_sync(
        preview_fill_async(result, output_dir, dpi=dpi, format=format)
    )
