from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docuflow.filling.docx_inspector import inspect_content_controls
from docuflow.filling.models import (
    DocxFillStrategy,
    FilledField,
    FillPlan,
    FormField,
    UnmatchedPolicy,
)
from docuflow.filling.planner import (
    _apply_unmapped_policy,
    _match_alias,
    _match_name,
    collect_data_fields,
    format_value,
    normalize_key,
)


def plan_docx_fill(
    path: str | Path,
    data: BaseModel | Mapping[str, Any],
    *,
    strategy: DocxFillStrategy = "auto",
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> tuple[FillPlan, list[FormField], str]:
    """Build a FillPlan for a DOCX document.

    Returns (plan, docx_fields, resolved_strategy).
    """
    resolved = _select_docx_strategy(path, strategy)

    if resolved != "content_controls":
        raise ValueError(f"Unsupported DOCX fill strategy: {resolved}")
    docx_fields = inspect_content_controls(path)
    plan = _build_content_controls_plan(
        docx_fields=docx_fields,
        data=data,
        formats=formats,
        skip_none=skip_none,
        unmatched=unmatched,
    )

    return plan, docx_fields, resolved


def _select_docx_strategy(path: str | Path, strategy: DocxFillStrategy) -> str:
    if strategy == "content_controls":
        return strategy
    controls = inspect_content_controls(path)
    if controls:
        return "content_controls"
    return "content_controls"  # will produce a zero-field plan with a clear error


def _build_content_controls_plan(
    *,
    docx_fields: list[FormField],
    data: BaseModel | Mapping[str, Any],
    formats: Mapping[str, str | Callable[[Any], Any]] | None,
    skip_none: bool,
    unmatched: UnmatchedPolicy,
) -> FillPlan:
    data_fields = collect_data_fields(data, skip_none=skip_none)
    by_name = {f.name: f for f in docx_fields}
    by_normalized = {normalize_key(f.name): f for f in docx_fields}
    assignments: dict[str, Any] = {}
    filled: dict[str, FilledField] = {}
    warnings: list[str] = []
    errors: list[str] = []
    unmapped_model: list[str] = []

    for df in data_fields:
        form_field, method = _match_alias(df, by_name, by_normalized)
        if form_field is None:
            form_field, method = _match_name(df, by_name, by_normalized)
        if form_field is None:
            unmapped_model.append(df.name)
            continue

        fv = format_value(df.value, form_field=form_field, format_spec=(formats or {}).get(df.name))
        assignments[form_field.name] = fv
        filled[df.name] = FilledField(
            field_name=df.name,
            value=df.value,
            formatted_value=fv,
            target_name=form_field.name,
            method=method,
        )

    assigned = set(assignments)
    unmapped_pdf = [f.name for f in docx_fields if f.name not in assigned]
    _apply_unmapped_policy(errors, warnings, unmapped_model, unmatched=unmatched, target_kind="DOCX content control")

    return FillPlan(
        strategy="content_controls",
        assignments=assignments,
        fields=filled,
        pdf_fields=docx_fields,
        unmapped_model_fields=unmapped_model,
        unmapped_pdf_fields=unmapped_pdf,
        warnings=warnings,
        errors=errors,
    )

