from __future__ import annotations

from pathlib import Path

from docuflow.metadata.models import (
    Comment,
    DocumentMetadataResult,
    Highlight,
    Hyperlink,
    Revision,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_COMMENTS_PART = "word/comments.xml"
_RELS_PART = "word/_rels/document.xml.rels"

# Highlight color map from WordprocessingML color names to hex.
_WML_COLORS: dict[str, str] = {
    "yellow": "#ffff00", "green": "#00ff00", "cyan": "#00ffff",
    "magenta": "#ff00ff", "blue": "#0000ff", "red": "#ff0000",
    "darkBlue": "#00008b", "darkCyan": "#008b8b", "darkGreen": "#006400",
    "darkMagenta": "#8b008b", "darkRed": "#8b0000", "darkYellow": "#808000",
    "darkGray": "#a9a9a9", "lightGray": "#d3d3d3", "black": "#000000",
    "white": "#ffffff", "none": "",
}


def extract_docx_metadata(path: str | Path) -> DocumentMetadataResult:
    result = DocumentMetadataResult(input_path=str(path))
    try:
        import xml.etree.ElementTree as ET
        import zipfile
    except ImportError:
        result.errors.append("Standard library modules zipfile/xml are unavailable.")
        return result

    try:
        zf = zipfile.ZipFile(str(path))
    except Exception as exc:
        result.errors.append(f"Could not open DOCX: {exc}")
        return result

    with zf:
        names = set(zf.namelist())

        # --- Comments ---
        if _COMMENTS_PART in names:
            try:
                xml_bytes = zf.read(_COMMENTS_PART)
                root = ET.fromstring(xml_bytes)  # noqa: S314 — DOCX content from local files
                for comment_el in root.findall(f"{{{_W}}}comment"):
                    author = comment_el.get(f"{{{_W}}}author", "")
                    date = comment_el.get(f"{{{_W}}}date", "")
                    text = _collect_text(comment_el)
                    result.comments.append(Comment(author=author, date=date, text=text))
            except Exception as exc:
                result.warnings.append(f"Could not parse comments: {exc}")

        # --- Hyperlinks and revisions from the document body ---
        if "word/document.xml" in names:
            try:
                doc_bytes = zf.read("word/document.xml")
                doc_root = ET.fromstring(doc_bytes)  # noqa: S314

                # Relationship map: rId → target URL
                rel_map: dict[str, str] = {}
                if _RELS_PART in names:
                    try:
                        rels_bytes = zf.read(_RELS_PART)
                        rels_root = ET.fromstring(rels_bytes)  # noqa: S314
                        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                        for rel in rels_root.findall(f"{{{rel_ns}}}Relationship"):
                            rel_map[rel.get("Id", "")] = rel.get("Target", "")
                    except Exception:  # noqa: S110 — rels are optional; missing rels leave URLs empty
                        pass

                _extract_hyperlinks(doc_root, rel_map, result)
                _extract_revisions(doc_root, result)
                _extract_highlights(doc_root, result)
            except Exception as exc:
                result.warnings.append(f"Could not parse document body: {exc}")

    return result


def _collect_text(element: object) -> str:
    parts: list[str] = []
    for t in element.iter(f"{{{_W}}}t"):  # type: ignore[union-attr]
        if t.text:
            parts.append(t.text)
    return " ".join(parts).strip()


def _extract_hyperlinks(
    root: object,
    rel_map: dict[str, str],
    result: DocumentMetadataResult,
) -> None:
    for hl in root.iter(f"{{{_W}}}hyperlink"):  # type: ignore[union-attr]
        rid = hl.get(f"{{{_R}}}id", "")
        url = rel_map.get(rid, "")
        # Fallback: anchor attribute for internal links
        anchor = hl.get(f"{{{_W}}}anchor", "")
        if not url and anchor:
            url = f"#bookmark:{anchor}"
        text = _collect_text(hl)
        result.hyperlinks.append(Hyperlink(url=url, text=text))


def _extract_revisions(root: object, result: DocumentMetadataResult) -> None:
    for ins in root.iter(f"{{{_W}}}ins"):  # type: ignore[union-attr]
        result.revisions.append(Revision(
            revision_type="insertion",
            author=ins.get(f"{{{_W}}}author", ""),
            date=ins.get(f"{{{_W}}}date", ""),
            text=_collect_text(ins),
        ))
    for del_el in root.iter(f"{{{_W}}}del"):  # type: ignore[union-attr]
        # Deleted text lives in w:delText elements.
        parts: list[str] = []
        for dt in del_el.iter(f"{{{_W}}}delText"):
            if dt.text:
                parts.append(dt.text)
        result.revisions.append(Revision(
            revision_type="deletion",
            author=del_el.get(f"{{{_W}}}author", ""),
            date=del_el.get(f"{{{_W}}}date", ""),
            text=" ".join(parts).strip(),
        ))


def _extract_highlights(root: object, result: DocumentMetadataResult) -> None:
    for rpr in root.iter(f"{{{_W}}}rPr"):  # type: ignore[union-attr]
        hl_el = rpr.find(f"{{{_W}}}highlight")
        if hl_el is None:
            continue
        color_name = hl_el.get(f"{{{_W}}}val", "")
        color_hex = _WML_COLORS.get(color_name, color_name)
        if not color_hex:
            continue
        # The parent of rPr is a w:r (run); collect its text.
        run = rpr.getparent() if hasattr(rpr, "getparent") else None
        text = _collect_text(run) if run is not None else ""
        result.highlights.append(Highlight(
            subtype="Highlight",
            color=color_hex,
            text=text,
        ))
