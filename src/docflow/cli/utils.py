from __future__ import annotations

import importlib

from pydantic import BaseModel

from docflow.templates.registry import TemplateRegistry


def load_schema(schema_str: str) -> type[BaseModel]:
    """Load a schema from a template name or Python dotted path.

    First tries to load as a template name (e.g., 'invoice').
    Falls back to importing from a dotted path (e.g., 'mymodule.Invoice').
    """
    registry = TemplateRegistry()
    try:
        return registry.load(schema_str)
    except FileNotFoundError:
        pass

    if "." not in schema_str:
        raise ValueError(
            f"Schema {schema_str!r} not found as template or Python path. "
            f"Use a template name or a dotted path like 'module.ClassName'."
        )

    module_path, _, class_name = schema_str.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(f"Cannot import module {module_path!r}: {exc}") from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"Module {module_path!r} has no attribute {class_name!r}")

    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        raise TypeError(f"{schema_str!r} is not a Pydantic BaseModel subclass")

    return cls
