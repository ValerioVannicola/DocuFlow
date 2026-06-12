from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, create_model

TYPE_MAP: dict[str, type] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "date": date,
    "datetime": datetime,
}


def _resolve_type(field_def: dict) -> tuple[type, Any]:
    """Resolve a field definition to (type, default_or_Field)."""
    type_str = field_def.get("type", "str")
    required = field_def.get("required", False)
    default = field_def.get("default", ...)
    description = field_def.get("description", "")

    if type_str == "list":
        item_fields = field_def.get("item_fields")
        if item_fields:
            item_model = _build_model_from_fields(
                f"_{field_def.get('_name', 'Item')}Item",
                item_fields,
            )
            resolved_type = list[item_model]
        else:
            item_type_str = field_def.get("item_type", "str")
            inner = TYPE_MAP.get(item_type_str, str)
            resolved_type = list[inner]
    elif type_str == "object":
        sub_fields = field_def.get("fields", {})
        resolved_type = _build_model_from_fields(
            f"_{field_def.get('_name', 'Sub')}",
            sub_fields,
        )
    else:
        resolved_type = TYPE_MAP.get(type_str, str)

    if not required and default is ...:
        resolved_type = resolved_type | None
        default = None

    if description:
        field_default = Field(default=default, description=description)
    elif default is not ...:
        field_default = default
    else:
        field_default = ...

    return (resolved_type, field_default)


def _build_model_from_fields(name: str, fields: dict) -> type[BaseModel]:
    """Build a Pydantic model from a fields dictionary."""
    model_fields: dict[str, Any] = {}
    for field_name, field_def in fields.items():
        if isinstance(field_def, dict):
            field_def["_name"] = field_name
            model_fields[field_name] = _resolve_type(field_def)
        else:
            model_fields[field_name] = (str, ...)
    return create_model(name, **model_fields)


def yaml_to_pydantic(template_data: dict) -> type[BaseModel]:
    """Convert a parsed YAML template dict to a Pydantic model class."""
    name = template_data.get("name", "DynamicSchema")
    model_name = "".join(word.capitalize() for word in name.split("_"))
    fields = template_data.get("fields", {})
    return _build_model_from_fields(model_name, fields)
