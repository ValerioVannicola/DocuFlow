from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers: build minimal test fixtures without real files
# ---------------------------------------------------------------------------

def _make_annotated_pdf(path: Path) -> None:
    """PDF with one comment, one highlight, one hyperlink, and one sig field."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )

    # 1. Draw a base page with reportlab
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "Test document")
    c.save()
    buf.seek(0)

    reader = PdfReader(buf)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    page = writer.pages[0]

    def _rect(x0, y0, x1, y1):
        return ArrayObject([FloatObject(x0), FloatObject(y0), FloatObject(x1), FloatObject(y1)])

    # Comment (/Text annotation)
    comment = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Rect"): _rect(72, 700, 120, 720),
        NameObject("/Contents"): TextStringObject("This is a comment"),
        NameObject("/T"): TextStringObject("Alice"),
        NameObject("/M"): TextStringObject("D:20240101120000"),
    })

    # Highlight
    highlight = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Highlight"),
        NameObject("/Rect"): _rect(72, 680, 300, 695),
        NameObject("/C"): ArrayObject([FloatObject(1.0), FloatObject(1.0), FloatObject(0.0)]),
        NameObject("/Contents"): TextStringObject("highlighted text"),
    })

    # Hyperlink
    action = DictionaryObject({
        NameObject("/S"): NameObject("/URI"),
        NameObject("/URI"): TextStringObject("https://example.com"),
    })
    link = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): _rect(72, 660, 200, 675),
        NameObject("/A"): action,
    })

    # Signature widget (unsigned — no /V)
    sig_widget = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Sig"),
        NameObject("/T"): TextStringObject("Signature1"),
        NameObject("/Rect"): _rect(72, 100, 300, 140),
    })

    annots = ArrayObject([comment, highlight, link, sig_widget])
    page[NameObject("/Annots")] = annots

    with path.open("wb") as f:
        writer.write(f)


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _make_docx_with_metadata(path: Path) -> None:
    """DOCX zip with comments, a hyperlink, a highlight, and tracked changes."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}">
  <w:body>
    <w:p>
      <w:hyperlink r:id="rId1" xmlns:r="{_R_NS}">
        <w:r><w:t>Click here</w:t></w:r>
      </w:hyperlink>
    </w:p>
    <w:p>
      <w:r>
        <w:rPr><w:highlight w:val="yellow"/></w:rPr>
        <w:t>important text</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:ins w:id="1" w:author="Bob" w:date="2024-03-01T10:00:00Z">
        <w:r><w:t>inserted text</w:t></w:r>
      </w:ins>
    </w:p>
    <w:p>
      <w:del w:id="2" w:author="Carol" w:date="2024-03-02T11:00:00Z">
        <w:r><w:delText>deleted text</w:delText></w:r>
      </w:del>
    </w:p>
  </w:body>
</w:document>"""

    rels_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{_PKG_NS}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="https://example.com" TargetMode="External"/>
</Relationships>"""

    comments_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:comments xmlns:w="{_W_NS}">
  <w:comment w:id="1" w:author="Alice" w:date="2024-01-01T09:00:00Z">
    <w:p><w:r><w:t>Review this section</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""

    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        zf.writestr("word/comments.xml", comments_xml)


# ---------------------------------------------------------------------------
# PDF metadata tests
# ---------------------------------------------------------------------------

class TestPdfMetadata:
    def test_comment_extracted(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert result.success
        assert len(result.comments) == 1
        assert result.comments[0].author == "Alice"
        assert "comment" in result.comments[0].text.lower()
        assert result.comments[0].page_number == 0

    def test_highlight_extracted(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert len(result.highlights) == 1
        h = result.highlights[0]
        assert h.subtype == "Highlight"
        assert h.color == "#ffff00"
        assert h.page_number == 0

    def test_hyperlink_extracted(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert len(result.hyperlinks) == 1
        assert result.hyperlinks[0].url == "https://example.com"

    def test_signature_field_extracted(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert len(result.signatures) == 1
        sig = result.signatures[0]
        assert sig.field_name == "Signature1"
        assert sig.signed is False

    def test_bbox_converted_to_top_left_origin(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert result.comments[0].bbox is not None
        # y0 must be >= 0 (top-left origin conversion)
        assert result.comments[0].bbox.y0 >= 0

    def test_missing_pypdf_returns_error(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "pypdf", None)  # type: ignore[arg-type]
        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(tmp_path / "missing.pdf")
        assert not result.success
        assert result.errors

    def test_no_annotations_returns_empty(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        from reportlab.pdfgen import canvas as rl_canvas

        pdf = tmp_path / "clean.pdf"
        c = rl_canvas.Canvas(str(pdf))
        c.drawString(72, 720, "No annotations here")
        c.save()

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)

        assert result.success
        assert not result.comments
        assert not result.highlights
        assert not result.hyperlinks
        assert not result.signatures

    def test_has_metadata_property(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        result = extract_pdf_metadata(pdf)
        assert result.has_metadata is True

    def test_extract_color_rgb(self):
        from pypdf.generic import ArrayObject, FloatObject

        from docuflow.metadata.pdf_extractor import _extract_color

        color = _extract_color(ArrayObject([FloatObject(1.0), FloatObject(0.0), FloatObject(0.0)]))
        assert color == "#ff0000"

    def test_extract_color_grayscale(self):
        from pypdf.generic import ArrayObject, FloatObject

        from docuflow.metadata.pdf_extractor import _extract_color

        color = _extract_color(ArrayObject([FloatObject(0.5)]))
        assert color == "#7f7f7f"


# ---------------------------------------------------------------------------
# DOCX metadata tests
# ---------------------------------------------------------------------------

class TestDocxMetadata:
    def test_comment_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        assert result.success
        assert len(result.comments) == 1
        c = result.comments[0]
        assert c.author == "Alice"
        assert "Review" in c.text

    def test_hyperlink_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        assert len(result.hyperlinks) >= 1
        urls = [h.url for h in result.hyperlinks]
        assert "https://example.com" in urls

    def test_hyperlink_text_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        hl = next(h for h in result.hyperlinks if h.url == "https://example.com")
        assert "Click" in hl.text

    def test_insertion_revision_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        insertions = [r for r in result.revisions if r.revision_type == "insertion"]
        assert len(insertions) == 1
        assert insertions[0].author == "Bob"
        assert "inserted" in insertions[0].text

    def test_deletion_revision_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        deletions = [r for r in result.revisions if r.revision_type == "deletion"]
        assert len(deletions) == 1
        assert deletions[0].author == "Carol"
        assert "deleted" in deletions[0].text

    def test_highlight_extracted(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        assert len(result.highlights) >= 1
        assert any(h.color == "#ffff00" for h in result.highlights)

    def test_no_comments_part(self, tmp_path):
        """DOCX without comments.xml returns empty comments gracefully."""
        doc_xml = f'<?xml version="1.0"?><w:document xmlns:w="{_W_NS}"><w:body/></w:document>'
        ct_xml = """<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>"""
        docx = tmp_path / "minimal.docx"
        with zipfile.ZipFile(str(docx), "w") as zf:
            zf.writestr("[Content_Types].xml", ct_xml)
            zf.writestr("word/document.xml", doc_xml)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)

        assert result.success
        assert result.comments == []

    def test_has_metadata_property(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.docx_extractor import extract_docx_metadata
        result = extract_docx_metadata(docx)
        assert result.has_metadata is True


# ---------------------------------------------------------------------------
# Top-level API dispatch tests
# ---------------------------------------------------------------------------

class TestExtractMetadataApi:
    def test_dispatches_pdf(self, tmp_path):
        pytest.importorskip("pypdf")
        pytest.importorskip("reportlab")
        pdf = tmp_path / "annotated.pdf"
        _make_annotated_pdf(pdf)

        from docuflow.metadata.api import extract_metadata
        result = extract_metadata(pdf)
        assert result.success
        assert result.has_metadata

    def test_dispatches_docx(self, tmp_path):
        docx = tmp_path / "test.docx"
        _make_docx_with_metadata(docx)

        from docuflow.metadata.api import extract_metadata
        result = extract_metadata(docx)
        assert result.success
        assert result.has_metadata

    def test_top_level_import(self):
        import docuflow
        assert callable(docuflow.extract_metadata)
        assert callable(docuflow.extract_metadata_async)
        assert docuflow.DocumentMetadataResult is not None
