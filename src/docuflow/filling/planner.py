from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from docuflow.filling.models import (
    FieldPlacement,
    FilledField,
    FillPlan,
    FormField,
    MatchStrategy,
    UnmatchedPolicy,
)


@dataclass(frozen=True)
class DataField:
    name: str
    value: Any
    aliases: tuple[str, ...] = ()
    description: str = ""
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def collect_data_fields(data: BaseModel | Mapping[str, Any], *, skip_none: bool = True) -> list[DataField]:
    """Convert a Pydantic instance or mapping into fillable field descriptors."""
    if isinstance(data, BaseModel):
        fields: list[DataField] = []
        model_fields = data.__class__.model_fields
        for name, info in model_fields.items():
            value = getattr(data, name)
            if skip_none and value is None:
                continue

            aliases = _field_aliases(name, info)
            required = bool(info.is_required()) if hasattr(info, "is_required") else False
            extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
            fields.append(
                DataField(
                    name=name,
                    value=value,
                    aliases=aliases,
                    description=info.description or "",
                    required=required,
                    metadata=dict(extra),
                )
            )
        return fields

    return [
        DataField(name=str(name), value=value, aliases=(str(name),), required=False)
        for name, value in data.items()
        if not (skip_none and value is None)
    ]


def dump_data(data: BaseModel | Mapping[str, Any], *, skip_none: bool = True) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        return data.model_dump(exclude_none=skip_none)
    return {
        str(name): value
        for name, value in data.items()
        if not (skip_none and value is None)
    }


def schema_name_for(data: BaseModel | Mapping[str, Any]) -> str:
    if isinstance(data, BaseModel):
        return data.__class__.__name__
    return "Mapping"


def build_acroform_plan(
    *,
    pdf_fields: list[FormField],
    data: BaseModel | Mapping[str, Any],
    field_map: Mapping[str, Any] | None = None,
    match_by: MatchStrategy = "auto",
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> FillPlan:
    data_fields = collect_data_fields(data, skip_none=skip_none)
    by_name = {field.name: field for field in pdf_fields}
    by_normalized = {normalize_key(field.name): field for field in pdf_fields}
    assignments: dict[str, Any] = {}
    filled: dict[str, FilledField] = {}
    warnings: list[str] = []
    errors: list[str] = []
    unmapped_model_fields: list[str] = []

    for data_field in data_fields:
        target = _explicit_acroform_target(data_field, field_map)
        method = "manual" if target else ""
        form_field = by_name.get(target or "") if target else None

        if form_field is None and match_by in ("auto", "alias"):
            form_field, method = _match_alias(data_field, by_name, by_normalized)

        if form_field is None and match_by in ("auto", "name"):
            form_field, method = _match_name(data_field, by_name, by_normalized)

        if form_field is None:
            unmapped_model_fields.append(data_field.name)
            continue

        formatted = format_value(
            data_field.value,
            form_field=form_field,
            format_spec=(formats or {}).get(data_field.name),
        )
        assignments[form_field.name] = formatted
        filled[data_field.name] = FilledField(
            field_name=data_field.name,
            value=data_field.value,
            formatted_value=formatted,
            target_name=form_field.name,
            page_number=form_field.page_number,
            bbox=form_field.bbox,
            method=method,
        )

    assigned_targets = set(assignments)
    unmapped_pdf_fields = [field.name for field in pdf_fields if field.name not in assigned_targets]
    _apply_unmapped_policy(
        errors,
        warnings,
        unmapped_model_fields,
        unmatched=unmatched,
        target_kind="PDF form field",
    )

    return FillPlan(
        strategy="acroform",
        assignments=assignments,
        fields=filled,
        pdf_fields=pdf_fields,
        unmapped_model_fields=unmapped_model_fields,
        unmapped_pdf_fields=unmapped_pdf_fields,
        warnings=warnings,
        errors=errors,
    )


def build_overlay_plan(
    *,
    data: BaseModel | Mapping[str, Any],
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> FillPlan:
    data_fields = collect_data_fields(data, skip_none=skip_none)
    placements: dict[str, FieldPlacement] = {}
    filled: dict[str, FilledField] = {}
    warnings: list[str] = []
    errors: list[str] = []
    unmapped_model_fields: list[str] = []

    for data_field in data_fields:
        placement = _explicit_overlay_placement(data_field, field_map)
        if placement is None:
            unmapped_model_fields.append(data_field.name)
            continue

        formatted = format_value(data_field.value, format_spec=(formats or {}).get(data_field.name))
        placements[data_field.name] = placement
        filled[data_field.name] = FilledField(
            field_name=data_field.name,
            value=data_field.value,
            formatted_value=formatted,
            target_name=data_field.name,
            page_number=placement.page_number,
            bbox=placement.bbox,
            placement=placement,
            method="manual_overlay",
        )

    _apply_unmapped_policy(
        errors,
        warnings,
        unmapped_model_fields,
        unmatched=unmatched,
        target_kind="overlay placement",
    )

    if not field_map:
        warnings.append(
            "Static PDF overlay filling requires field_map placements. "
            "Automatic blank-space detection only runs when detect_blank_spaces=True."
        )

    return FillPlan(
        strategy="overlay",
        placements=placements,
        fields=filled,
        unmapped_model_fields=unmapped_model_fields,
        warnings=warnings,
        errors=errors,
    )


def format_value(
    value: Any,
    *,
    form_field: FormField | None = None,
    format_spec: str | Callable[[Any], Any] | None = None,
) -> Any:
    if callable(format_spec):
        return format_spec(value)
    if format_spec:
        if "{" in format_spec:
            return format_spec.format(value=value)
        return format(value, format_spec)

    if form_field and form_field.field_type == "checkbox" and isinstance(value, bool):
        if not value:
            return "Off"
        return form_field.options[0] if form_field.options else "Yes"

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _field_aliases(name: str, info: Any) -> tuple[str, ...]:
    aliases: list[str] = [name]
    for attr in ("alias", "serialization_alias", "validation_alias"):
        alias = getattr(info, attr, None)
        if isinstance(alias, str):
            aliases.append(alias)
    extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
    for key in ("pdf_field", "form_field"):
        alias = extra.get(key)
        if isinstance(alias, str):
            aliases.append(alias)
    pdf_fields = extra.get("pdf_fields", [])
    if isinstance(pdf_fields, str):
        aliases.append(pdf_fields)
    else:
        aliases.extend(alias for alias in pdf_fields if isinstance(alias, str))
    return tuple(dict.fromkeys(aliases))


def _explicit_acroform_target(
    data_field: DataField,
    field_map: Mapping[str, Any] | None,
) -> str | None:
    target = _field_map_value(data_field, field_map)
    if isinstance(target, str):
        return target
    if isinstance(target, Mapping):
        for key in ("target_name", "pdf_field", "form_field", "target"):
            value = target.get(key)
            if isinstance(value, str):
                return value
    for key in ("pdf_field", "form_field"):
        value = data_field.metadata.get(key)
        if isinstance(value, str):
            return value
    return None


def _explicit_overlay_placement(
    data_field: DataField,
    field_map: Mapping[str, Any] | None,
) -> FieldPlacement | None:
    target = _field_map_value(data_field, field_map)
    if target is None:
        target = data_field.metadata.get("placement")
    if isinstance(target, FieldPlacement):
        return target
    if not isinstance(target, Mapping):
        return None
    if "placement" in target and isinstance(target["placement"], Mapping):
        target = target["placement"]
    if "bbox" not in target:
        coordinate_keys = {"x0", "y0", "x1", "y1"}
        if coordinate_keys.issubset(target.keys()):
            target = {**target, "bbox": {key: target[key] for key in coordinate_keys}}
    return FieldPlacement.model_validate(target)


def _field_map_value(data_field: DataField, field_map: Mapping[str, Any] | None) -> Any:
    if not field_map:
        return None
    for key in (data_field.name, *data_field.aliases):
        if key in field_map:
            return field_map[key]
    return None


def _match_alias(
    data_field: DataField,
    by_name: dict[str, FormField],
    by_normalized: dict[str, FormField],
) -> tuple[FormField | None, str]:
    for alias in data_field.aliases:
        if alias in by_name:
            return by_name[alias], "exact_alias"
    for alias in data_field.aliases:
        field = by_normalized.get(normalize_key(alias))
        if field is not None:
            return field, "normalized_alias"
    return None, ""


def _match_name(
    data_field: DataField,
    by_name: dict[str, FormField],
    by_normalized: dict[str, FormField],
) -> tuple[FormField | None, str]:
    if data_field.name in by_name:
        return by_name[data_field.name], "exact_name"
    field = by_normalized.get(normalize_key(data_field.name))
    if field is not None:
        return field, "normalized_name"
    return None, ""


def _apply_unmapped_policy(
    errors: list[str],
    warnings: list[str],
    unmapped_model_fields: list[str],
    *,
    unmatched: UnmatchedPolicy,
    target_kind: str,
) -> None:
    if not unmapped_model_fields or unmatched == "ignore":
        return
    message = (
        f"No {target_kind} was found for model field(s): "
        f"{', '.join(unmapped_model_fields)}"
    )
    if unmatched == "error":
        errors.append(message)
    else:
        warnings.append(message)
