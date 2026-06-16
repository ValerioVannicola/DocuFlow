from __future__ import annotations

from pathlib import Path

from docuflow.filling.models import FormField

_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"


def _qn(tag: str) -> str:
    from docx.oxml.ns import qn  # type: ignore[import-untyped]
    return qn(tag)


def inspect_content_controls(path: str | Path) -> list[FormField]:
    """Discover all SDT content controls in a DOCX document."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document(str(path))
    fields: list[FormField] = []
    seen: set[str] = set()

    for sdt in doc.element.iter(_qn("w:sdt")):
        props = sdt.find(_qn("w:sdtPr"))
        tag, alias, ctrl_type, options, current = _parse_sdt(props, sdt)

        name = tag or alias
        if not name:
            name = f"control_{len(fields)}"
        # Deduplicate — Word may have the same control in header + body
        if name in seen:
            continue
        seen.add(name)

        fields.append(
            FormField(
                name=name,
                field_type=ctrl_type,
                options=options,
                current_value=current,
            )
        )

    return fields


def _parse_sdt(
    props,  # type: ignore[type-arg]
    sdt,  # type: ignore[type-arg]
) -> tuple[str, str, str, list[str], str]:
    """Extract (tag, alias, control_type, options, current_value) from an SDT element."""
    tag = alias = ""
    ctrl_type = "plainText"
    options: list[str] = []

    if props is not None:
        tag_el = props.find(_qn("w:tag"))
        alias_el = props.find(_qn("w:alias"))
        if tag_el is not None:
            tag = tag_el.get(_qn("w:val"), "")
        if alias_el is not None:
            alias = alias_el.get(_qn("w:val"), "")

        # Modern checkbox (w14 namespace)
        cb14 = props.find(f"{{{_W14_NS}}}checkbox")
        if cb14 is not None:
            ctrl_type = "checkbox"
        elif props.find(_qn("w:dropDownList")) is not None:
            ctrl_type = "dropdown"
            dd = props.find(_qn("w:dropDownList"))
            options = [
                li.get(_qn("w:val"), "")
                for li in dd.findall(_qn("w:listItem"))
            ]
        elif props.find(_qn("w:comboBox")) is not None:
            ctrl_type = "comboBox"
            cb = props.find(_qn("w:comboBox"))
            options = [
                li.get(_qn("w:val"), "")
                for li in cb.findall(_qn("w:listItem"))
            ]
        elif props.find(_qn("w:date")) is not None:
            ctrl_type = "date"
        elif props.find(_qn("w:text")) is not None:
            ctrl_type = "plainText"

    content_el = sdt.find(_qn("w:sdtContent"))
    current = ""
    if content_el is not None:
        current = "".join(t.text or "" for t in content_el.iter(_qn("w:t")))

    return tag, alias, ctrl_type, options, current
