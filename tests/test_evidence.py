from __future__ import annotations

from docuflow.documents.models import (
    Block,
    BlockType,
    BoundingBox,
    Document,
    DocumentMetadata,
    Page,
)
from docuflow.extraction.evidence import _leaf_strings, attach_evidence


def _doc(*block_texts: str) -> Document:
    blocks = [
        Block(
            block_id=f"b{i}",
            block_type=BlockType.TEXT,
            text=text,
            bbox=BoundingBox(x0=72, y0=72 + i * 30, x1=520, y1=90 + i * 30),
        )
        for i, text in enumerate(block_texts)
    ]
    page_text = "\n".join(block_texts)
    return Document(
        id="doc-evidence",
        metadata=DocumentMetadata(
            file_name="t.pdf", file_path="/t.pdf", mime_type="application/pdf",
        ),
        pages=[Page(page_number=0, width=595, height=842, text=page_text, blocks=blocks)],
        raw_text=page_text,
    )


def test_leaf_strings_flattens_lists_and_nested_objects():
    value = [
        {"code": "QUA/DEV/2025/00775", "description": "first deviation"},
        {"code": "QUA/DEV/2025/00536", "description": None},
    ]
    leaves = _leaf_strings(value)
    assert "QUA/DEV/2025/00775" in leaves
    assert "QUA/DEV/2025/00536" in leaves
    assert "first deviation" in leaves
    # None and booleans are not locatable text and must be skipped.
    assert _leaf_strings(None) == []
    assert _leaf_strings(True) == []
    assert _leaf_strings(["x", True, None, "y"]) == ["x", "y"]


def test_list_of_scalars_grounds_each_element():
    """A List[str] field must not be located as its Python repr."""
    doc = _doc("Manufacturing date 23/07/2025", "Expiry 07/2027")
    evidences = attach_evidence(doc, "manufacturing_date", ["23/07/2025"], {})
    assert len(evidences) == 1
    assert evidences[0].text == "23/07/2025"
    assert evidences[0].bbox is not None  # grounded, not a repr fallback


def test_nested_object_list_grounds_each_code():
    """The reported bug: List[DeviationReference] could not be visualised."""
    doc = _doc(
        "Deviation QUA/DEV/2025/00775 was opened to ensure traceability.",
        "A first deviation QUA/DEV/2025/00536 was opened in June.",
    )
    value = [
        {"code": "QUA/DEV/2025/00775", "description": "opened to ensure traceability"},
        {"code": "QUA/DEV/2025/00536", "description": "opened in June"},
    ]
    evidences = attach_evidence(doc, "deviations_referenced", value, {})

    located = {e.text: e for e in evidences}
    assert "QUA/DEV/2025/00775" in located
    assert "QUA/DEV/2025/00536" in located
    # Each grounded leaf carries a real box so highlight_fields can draw it.
    assert all(e.bbox is not None or e.rects for e in evidences)
    # The two codes are on different blocks → distinct boxes.
    assert located["QUA/DEV/2025/00775"].bbox != located["QUA/DEV/2025/00536"].bbox


def test_unlocatable_composite_falls_back_to_hint():
    """If no leaf can be located, behaviour falls back to the hint text/page."""
    doc = _doc("Totally unrelated document content.")
    value = [{"code": "NOT-IN-DOC", "description": "missing"}]
    evidences = attach_evidence(
        doc, "deviations_referenced", value, {"page": 2, "text": "summary note"},
    )
    assert len(evidences) == 1
    assert evidences[0].text == "summary note"
    assert evidences[0].page_number == 2


def test_scalar_field_behaviour_unchanged():
    doc = _doc("Invoice from Acme Corp")
    evidences = attach_evidence(doc, "supplier_name", "Acme Corp", {"page": 0, "text": "Acme Corp"})
    assert len(evidences) == 1
    assert evidences[0].text == "Acme Corp"
    assert evidences[0].bbox is not None
