from __future__ import annotations

from pathlib import Path
from typing import Any

from docuflow.documents.models import BoundingBox
from docuflow.metadata.models import (
    Comment,
    DocumentMetadataResult,
    Highlight,
    Hyperlink,
    Signature,
)

# PDF annotation subtypes we care about, mapped to our categories.
_HIGHLIGHT_SUBTYPES = {"Highlight", "Underline", "StrikeOut", "Squiggly", "Ink"}
_COMMENT_SUBTYPES = {"Text", "FreeText", "Popup"}
_LINK_SUBTYPES = {"Link"}
_WIDGET_SUBTYPE = "Widget"


def extract_pdf_metadata(path: str | Path) -> DocumentMetadataResult:
    result = DocumentMetadataResult(input_path=str(path))
    try:
        from pypdf import PdfReader
    except ImportError:
        result.errors.append(
            "pypdf is required for PDF metadata extraction. "
            "Install it with: pip install 'docuflow[forms]'"
        )
        return result

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        result.errors.append(f"Could not open PDF: {exc}")
        return result

    for page_num, page in enumerate(reader.pages):
        page_height = float(page.mediabox.top) - float(page.mediabox.bottom)
        annots_ref = page.get("/Annots")
        if annots_ref is None:
            continue

        try:
            annots = annots_ref
            if hasattr(annots, "get_object"):
                annots = annots.get_object()
        except Exception:
            result.warnings.append(f"Page {page_num}: could not resolve /Annots.")
            continue

        for annot_ref in annots:
            try:
                annot = annot_ref
                if hasattr(annot_ref, "get_object"):
                    annot = annot_ref.get_object()
                _process_annotation(annot, page_num, page_height, result)
            except Exception as exc:
                result.warnings.append(f"Page {page_num}: skipped annotation — {exc}")

    return result


def _pdf_rect_to_bbox(rect: Any, page_height: float) -> BoundingBox | None:
    """Convert PDF /Rect [llx lly urx ury] to top-left-origin BoundingBox."""
    try:
        llx, lly, urx, ury = (float(v) for v in rect)
        return BoundingBox(
            x0=llx,
            y0=page_height - ury,
            x1=urx,
            y1=page_height - lly,
        )
    except Exception:
        return None


def _str(val: Any) -> str:
    if val is None:
        return ""
    try:
        return str(val)
    except Exception:
        return ""


def _process_annotation(
    annot: Any,
    page_num: int,
    page_height: float,
    result: DocumentMetadataResult,
) -> None:
    subtype = _str(annot.get("/Subtype")).lstrip("/")
    rect = annot.get("/Rect")
    bbox = _pdf_rect_to_bbox(rect, page_height) if rect is not None else None

    if subtype in _COMMENT_SUBTYPES:
        result.comments.append(Comment(
            page_number=page_num,
            author=_str(annot.get("/T")),
            date=_str(annot.get("/M")),
            text=_str(annot.get("/Contents")),
            bbox=bbox,
        ))

    elif subtype in _HIGHLIGHT_SUBTYPES:
        color = _extract_color(annot.get("/C"))
        result.highlights.append(Highlight(
            page_number=page_num,
            subtype=subtype if subtype in _HIGHLIGHT_SUBTYPES else "Highlight",  # type: ignore[arg-type]
            color=color,
            text=_str(annot.get("/Contents")),
            bbox=bbox,
        ))

    elif subtype in _LINK_SUBTYPES:
        url = ""
        action = annot.get("/A")
        if action is not None:
            if hasattr(action, "get_object"):
                action = action.get_object()
            action_type = _str(action.get("/S")).lstrip("/")
            if action_type == "URI":
                url = _str(action.get("/URI"))
            elif action_type == "GoTo":
                dest = action.get("/D")
                url = f"internal:{_str(dest)}"
        result.hyperlinks.append(Hyperlink(
            page_number=page_num,
            url=url,
            text=_str(annot.get("/Contents")),
            bbox=bbox,
        ))

    elif subtype == _WIDGET_SUBTYPE:
        field_type = _str(annot.get("/FT")).lstrip("/")
        if field_type == "Sig":
            sig_value = annot.get("/V")
            signed = sig_value is not None
            signer = ""
            date = ""
            if signed and hasattr(sig_value, "get_object"):
                sig_obj = sig_value.get_object()
                signer = _str(sig_obj.get("/Name"))
                date = _str(sig_obj.get("/M"))
            result.signatures.append(Signature(
                page_number=page_num,
                field_name=_str(annot.get("/T")),
                signer=signer,
                date=date,
                signed=signed,
                bbox=bbox,
            ))


def _extract_color(color_array: Any) -> str:
    if color_array is None:
        return ""
    try:
        values = [float(v) for v in color_array]
        if len(values) == 3:
            r, g, b = (int(v * 255) for v in values)
            return f"#{r:02x}{g:02x}{b:02x}"
        if len(values) == 1:
            g = int(values[0] * 255)
            return f"#{g:02x}{g:02x}{g:02x}"
    except Exception:  # noqa: S110 — malformed color arrays are silently ignored
        pass
    return ""
