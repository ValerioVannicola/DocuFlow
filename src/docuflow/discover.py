from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, create_model

from docuflow._sync import run_sync
from docuflow.extraction.llm.base import LLMAdapter

DISCOVER_SYSTEM_PROMPT = """You are a document analysis assistant. Given the text of a document, \
identify ALL extractable fields — every piece of structured data that could be pulled from this \
document type.

For each field, provide:
- name: a snake_case Python variable name
- type: one of "str", "float", "int", "bool", "date", "list[str]"
- required: true if the field is always present in this document type, false if optional
- description: what this field represents

Return ONLY a JSON object:
{
  "document_type": "invoice" or "contract" or "receipt" etc,
  "description": "one-line description of the document",
  "fields": [
    {"name": "field_name", "type": "str", "required": true, "description": "what it is"},
    ...
  ]
}

Be thorough — include every field you can identify. Use clear, descriptive names. \
Return ONLY the JSON object, nothing else."""

TYPE_MAP: dict[str, type] = {
    "str": str,
    "string": str,
    "float": float,
    "int": int,
    "integer": int,
    "bool": bool,
    "boolean": bool,
    "date": str,
    "datetime": str,
    "list[str]": list[str],
    "list": list[str],
}


class DiscoveredField(BaseModel):
    name: str
    type: str = "str"
    required: bool = True
    description: str = ""


class DiscoveryResult(BaseModel):
    document_type: str = ""
    description: str = ""
    fields: list[DiscoveredField] = Field(default_factory=list)
    schema_class: Any = None
    yaml_template: str = ""

    model_config = {"arbitrary_types_allowed": True}


def _build_pydantic_model(result: DiscoveryResult) -> type[BaseModel]:
    model_name = "".join(w.capitalize() for w in result.document_type.split("_")) or "Document"

    field_definitions: dict[str, Any] = {}
    for f in result.fields:
        python_type = TYPE_MAP.get(f.type, str)
        if f.required:
            field_definitions[f.name] = (python_type, Field(description=f.description))
        else:
            field_definitions[f.name] = (
                python_type | None,
                Field(default=None, description=f.description),
            )

    return create_model(model_name, **field_definitions)


def _build_yaml_template(result: DiscoveryResult) -> str:
    lines = [
        f"name: {result.document_type}",
        'version: "1.0"',
        f"description: \"{result.description}\"",
        "fields:",
    ]
    for f in result.fields:
        yaml_type = f.type if f.type in ("str", "int", "float", "bool", "date") else "str"
        lines.append(f"  {f.name}:")
        lines.append(f"    type: {yaml_type}")
        lines.append(f"    required: {'true' if f.required else 'false'}")
        if f.description:
            lines.append(f"    description: \"{f.description}\"")
    return "\n".join(lines)


async def discover_schema(
    path: str,
    llm: LLMAdapter | None = None,
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
) -> DiscoveryResult:
    from docuflow.ingestion.local import ingest_file

    document = await ingest_file(path)

    if parser == "pdfplumber":
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser

        document = await PdfplumberParser().parse(document)
    elif parser == "tesseract":
        from docuflow.parsing.tesseract_parser import TesseractParser

        document = await TesseractParser().parse(document)
    elif parser == "docling":
        from docuflow.parsing.docling_parser import DoclingParser

        document = await DoclingParser().parse(document)
    elif parser == "smart":
        from docuflow.parsing.smart_parser import SmartParser

        document = await SmartParser().parse(document)

    if llm is None:
        from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

        llm = LiteLLMAdapter(model=model)

    text = document.raw_text[:8000]

    messages = [
        {"role": "system", "content": DISCOVER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyze this document and identify all extractable fields:\n\n{text}"},
    ]

    response = await llm.complete(
        messages, temperature=0.0, response_format={"type": "json_object"},
    )

    content = response.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    parsed = json.loads(content)

    fields = [
        DiscoveredField(
            name=f.get("name", ""),
            type=f.get("type", "str"),
            required=f.get("required", True),
            description=f.get("description", ""),
        )
        for f in parsed.get("fields", [])
        if f.get("name")
    ]

    result = DiscoveryResult(
        document_type=parsed.get("document_type", "document"),
        description=parsed.get("description", ""),
        fields=fields,
    )

    result.schema_class = _build_pydantic_model(result)
    result.yaml_template = _build_yaml_template(result)

    return result


def discover_schema_sync(
    path: str,
    llm: LLMAdapter | None = None,
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
) -> DiscoveryResult:
    return run_sync(discover_schema(path, llm, model, parser))
