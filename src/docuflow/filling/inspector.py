from __future__ import annotations

from pathlib import Path
from typing import Any

from docuflow.documents.models import BoundingBox
from docuflow.filling.models import FormField


def inspect_pdf_form(path: str | Path) -> list[FormField]:
    """Return writable AcroForm widget fields discovered in a PDF."""
    pdf_reader_cls = _require_pypdf_reader()
    reader = pdf_reader_cls(str(path))
    fields: list[FormField] = []
    seen: set[tuple[str, int | None]] = set()

    for page_number, page in enumerate(reader.pages):
        page_height = _page_height(page)
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue

            name = _field_name(annotation)
            if not name:
                continue

            key = (name, page_number)
            if key in seen:
                continue
            seen.add(key)

            field_type = _field_type(annotation)
            rect = annotation.get("/Rect")
            fields.append(
                FormField(
                    name=name,
                    field_type=field_type,
                    page_number=page_number,
                    bbox=_bbox_from_pdf_rect(rect, page_height) if rect else None,
                    options=_field_options(annotation),
                    current_value=_primitive(annotation.get("/V")),
                    required=_field_required(annotation),
                )
            )

    return fields


def _require_pypdf_reader() -> Any:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError(
            "PDF form filling requires pypdf. Install it with: "
            "pip install 'docuflow[forms]'"
        ) from exc
    return PdfReader


def _field_name(annotation: Any) -> str:
    value = annotation.get("/T")
    if value:
        return str(value)
    parent = annotation.get("/Parent")
    if parent:
        parent_obj = parent.get_object()
        value = parent_obj.get("/T")
        if value:
            child = annotation.get("/T")
            return f"{value}.{child}" if child else str(value)
    return ""


def _field_type(annotation: Any) -> str:
    value = annotation.get("/FT")
    parent = annotation.get("/Parent")
    if value is None and parent:
        value = parent.get_object().get("/FT")
    if value == "/Tx":
        return "text"
    if value == "/Btn":
        return "checkbox" if _field_options(annotation) else "button"
    if value == "/Ch":
        return "choice"
    if value == "/Sig":
        return "signature"
    return "unknown"


def _field_options(annotation: Any) -> list[str]:
    options: list[str] = []
    for key in ("/Opt", "/AP"):
        value = annotation.get(key)
        if value is None:
            continue
        if key == "/Opt":
            return [_primitive(item) for item in value]
        if key == "/AP":
            normal = value.get("/N") if hasattr(value, "get") else None
            if hasattr(normal, "keys"):
                options.extend(str(option).lstrip("/") for option in normal)
    return [option for option in options if option != "Off"]


def _field_required(annotation: Any) -> bool:
    flags = int(annotation.get("/Ff", 0) or 0)
    return bool(flags & 2)


def _page_height(page: Any) -> float:
    media_box = page.mediabox
    return float(media_box.top) - float(media_box.bottom)


def _bbox_from_pdf_rect(rect: Any, page_height: float) -> BoundingBox:
    values = [float(item) for item in rect]
    x0 = min(values[0], values[2])
    y0 = min(values[1], values[3])
    x1 = max(values[0], values[2])
    y1 = max(values[1], values[3])
    return BoundingBox(
        x0=x0,
        y0=page_height - y1,
        x1=x1,
        y1=page_height - y0,
    )


def _primitive(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return [_primitive(item) for item in value]
    text = str(value)
    return text[1:] if text.startswith("/") else text
