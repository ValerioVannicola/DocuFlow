from __future__ import annotations

from pathlib import Path

from docuflow.filling.models import FillingResult

_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"


def _qn(tag: str) -> str:
    from docx.oxml.ns import qn  # type: ignore[import-untyped]
    return qn(tag)


def write_content_controls(
    input_path: str | Path,
    output_path: str | Path,
    result: FillingResult,
) -> list[str]:
    """Write planned values into DOCX content controls (SDT elements)."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document(str(input_path))
    warnings: list[str] = []
    filled = {f.target_name: f for f in result.fields.values() if f.status == "filled"}
    written: set[str] = set()

    for sdt in doc.element.iter(_qn("w:sdt")):
        props = sdt.find(_qn("w:sdtPr"))
        if props is None:
            continue
        tag_el = props.find(_qn("w:tag"))
        alias_el = props.find(_qn("w:alias"))
        tag = tag_el.get(_qn("w:val"), "") if tag_el is not None else ""
        alias = alias_el.get(_qn("w:val"), "") if alias_el is not None else ""
        name = tag or alias
        if not name or name not in filled:
            continue
        if name in written:
            continue

        field = filled[name]
        content_el = sdt.find(_qn("w:sdtContent"))
        if content_el is None:
            warnings.append(f"Field '{name}': sdtContent missing, skipped.")
            continue

        cb14 = props.find(f"{{{_W14_NS}}}checkbox")
        if cb14 is not None:
            _fill_checkbox(cb14, content_el, bool(field.value))
        elif props.find(_qn("w:dropDownList")) is not None or props.find(_qn("w:comboBox")) is not None:
            _fill_text(content_el, str(field.formatted_value))
        else:
            _fill_text(content_el, str(field.formatted_value))

        if result.flatten:
            _flatten_sdt(sdt)

        written.add(name)

    for name in filled:
        if name not in written:
            warnings.append(f"Field '{name}' was planned but no matching content control was found.")

    doc.save(str(output_path))
    return warnings


def write_template(
    input_path: str | Path,
    output_path: str | Path,
    result: FillingResult,
) -> list[str]:
    """Render a docxtpl Jinja2 DOCX template with planned values."""
    from docxtpl import DocxTemplate  # type: ignore[import-untyped]

    tpl = DocxTemplate(str(input_path))
    context = {
        f.target_name: f.formatted_value
        for f in result.fields.values()
        if f.status == "filled"
    }
    tpl.render(context)
    tpl.save(str(output_path))
    return []


def _fill_text(content_el, text: str) -> None:  # type: ignore[type-arg]
    """Replace all w:t content in an sdtContent element with a single text value."""
    from docx.oxml import OxmlElement  # type: ignore[import-untyped]

    t_els = list(content_el.iter(_qn("w:t")))
    if t_els:
        t_els[0].text = text
        # Preserve space if needed
        if text and (text[0] == " " or text[-1] == " "):
            t_els[0].set(
                "{http://www.w3.org/XML/1998/namespace}space", "preserve"
            )
        for extra in t_els[1:]:
            extra.text = ""
    else:
        # No existing run — create a minimal paragraph > run > t structure
        para = content_el.find(_qn("w:p"))
        if para is None:
            para = OxmlElement("w:p")
            content_el.append(para)
        run = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        run.append(t)
        para.append(run)


def _fill_checkbox(
    cb14,  # type: ignore[type-arg]
    content_el,  # type: ignore[type-arg]
    checked: bool,
) -> None:
    """Set a w14:checkbox control's state and update its display character."""
    checked_el = cb14.find(f"{{{_W14_NS}}}checked")
    if checked_el is not None:
        checked_el.set(f"{{{_W14_NS}}}val", "1" if checked else "0")

    # Update the display character — Word uses font-specific characters.
    # Fall back to standard Unicode box characters.
    for t in content_el.iter(_qn("w:t")):
        char = t.text or ""
        # Wingdings / Wingdings 2 checkbox chars or Unicode fallback
        if char in ("☐", "☒", "☑", "", "", "", ""):
            t.text = "☑" if checked else "☐"
            break
        # If we can't identify the current char, set Unicode box
        if not char or len(char) == 1:
            t.text = "☑" if checked else "☐"
            break


def _flatten_sdt(sdt) -> None:  # type: ignore[type-arg]
    """Replace a w:sdt element with the children of its w:sdtContent (remove the wrapper)."""
    parent = sdt.getparent()
    if parent is None:
        return
    content_el = sdt.find(_qn("w:sdtContent"))
    if content_el is None:
        parent.remove(sdt)
        return
    idx = list(parent).index(sdt)
    parent.remove(sdt)
    for i, child in enumerate(list(content_el)):
        parent.insert(idx + i, child)
