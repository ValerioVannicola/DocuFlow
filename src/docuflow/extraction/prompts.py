from __future__ import annotations

import json

from pydantic import BaseModel, Field


def _schema_to_field_descriptions(schema: type[BaseModel]) -> str:
    lines: list[str] = []
    json_schema = schema.model_json_schema()
    properties = json_schema.get("properties", {})
    required = set(json_schema.get("required", []))
    for name, prop in properties.items():
        ftype = prop.get("type", "string")
        desc = prop.get("description", "")
        req = " (required)" if name in required else " (optional)"
        line = f"- {name}: {ftype}{req}"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


def _build_example_output(schema: type[BaseModel]) -> str:
    json_schema = schema.model_json_schema()
    properties = json_schema.get("properties", {})
    data_example = {}
    evidence_example = {}
    for name, prop in properties.items():
        ftype = prop.get("type", "string")
        if ftype == "number" or ftype == "integer":
            data_example[name] = 0.0
        elif ftype == "boolean":
            data_example[name] = False
        elif ftype == "array":
            data_example[name] = []
        else:
            data_example[name] = f"<{name} value>"
        evidence_example[name] = {
            "page": 0,
            "text": f"<exact quote for {name}>",
            "confidence": 0.95,
        }
    return json.dumps({"data": data_example, "evidence": evidence_example}, indent=2)


class ExtractionResponse(BaseModel):
    data: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


EXTRACTION_SYSTEM_PROMPT = """You are a precise document data extraction assistant. \
Your task is to extract structured data from document text according to a given schema.

Rules:
1. Extract ONLY values that are explicitly present in the document text.
2. Do NOT invent, guess, or hallucinate values.
3. For each field, provide the extracted value and evidence from the source text.
4. If a field's value cannot be found in the document, set it to null.
5. Return ONLY valid JSON — no markdown, no explanation, no extra text.
6. For evidence, quote the EXACT text snippet from the document that supports each value.
7. Use the exact field names from the schema — do not rename or reformat them.
8. Values in "data" MUST match the JSON Schema types exactly: numbers as JSON numbers
   without currency symbols, commas, or percent signs; arrays as JSON arrays; objects as
   JSON objects; booleans as booleans. Keep formatting such as "$1,234.00" or "8.25%"
   only inside evidence text, not in data values.

Output format — you MUST return exactly this JSON structure:
{
  "data": { <field values matching the schema> },
  "evidence": {
    "<field_name>": {
      "page": <0-indexed page number>,
      "text": "<exact quote from source>",
      "confidence": <0.0 to 1.0>
    }
  }
}

Confidence scoring:
- 1.0: the value is explicitly and unambiguously stated in the document
- 0.7-0.9: the value is clearly present but requires minor interpretation
- 0.4-0.6: the value is inferred or partially visible
- 0.0-0.3: low certainty, the value is a guess

Only include evidence entries for fields where you found a value. \
Return ONLY the JSON object, nothing else."""


VISION_EXTRACTION_SYSTEM_PROMPT = """You are a precise document data extraction assistant. \
You will receive page images of a document. Your task is to extract structured data from \
the document images according to a given schema.

Rules:
1. Extract ONLY values that are explicitly visible in the document images.
2. Do NOT invent, guess, or hallucinate values.
3. For each field, provide the extracted value and evidence.
4. If a field's value cannot be found in the document, set it to null.
5. Return ONLY valid JSON — no markdown, no explanation, no extra text.
6. For evidence, quote the text as you read it from the image.
7. Use the exact field names from the schema — do not rename or reformat them.
8. Values in "data" MUST match the JSON Schema types exactly: numbers as JSON numbers
   without currency symbols, commas, or percent signs; arrays as JSON arrays; objects as
   JSON objects; booleans as booleans. Keep formatting such as "$1,234.00" or "8.25%"
   only inside evidence text, not in data values.

Output format — you MUST return exactly this JSON structure:
{
  "data": { <field values matching the schema> },
  "evidence": {
    "<field_name>": {
      "page": <0-indexed page number>,
      "text": "<value as read from the image>",
      "confidence": <0.0 to 1.0>
    }
  }
}

Confidence scoring:
- 1.0: the value is clearly and unambiguously visible in the image
- 0.7-0.9: the value is visible but requires minor interpretation
- 0.4-0.6: the value is partially visible or hard to read
- 0.0-0.3: low certainty, the value is a guess

Only include evidence entries for fields where you found a value. \
Return ONLY the JSON object, nothing else."""


JSON_REPAIR_PROMPT = (
    "Your previous response was not valid JSON. "
    "Please return ONLY a valid JSON object with 'data' and 'evidence' keys. "
    "No markdown code fences, no explanation — just the raw JSON object."
)


def _build_system_prompt(base_prompt: str, context: str | None = None) -> str:
    if not context:
        return base_prompt
    return f"{base_prompt}\n\nDomain context:\n{context}"


def build_extraction_prompt(
    schema: type[BaseModel],
    document_text: str,
    page_texts: list[str] | None = None,
    context: str | None = None,
) -> list[dict]:
    field_desc = _schema_to_field_descriptions(schema)
    json_schema = json.dumps(schema.model_json_schema(), indent=2)
    example = _build_example_output(schema)

    user_content_parts = [f"## Schema Fields\n{field_desc}\n"]
    user_content_parts.append(f"## JSON Schema\n```json\n{json_schema}\n```\n")
    user_content_parts.append(f"## Expected Output Format\n```json\n{example}\n```\n")

    if page_texts:
        for i, page_text in enumerate(page_texts):
            user_content_parts.append(f"## Page {i}\n{page_text}\n")
    else:
        user_content_parts.append(f"## Document Text\n{document_text}\n")

    user_content_parts.append(
        "Extract the data according to the schema. "
        "Return ONLY the JSON object with 'data' and 'evidence' keys."
    )

    return [
        {"role": "system", "content": _build_system_prompt(EXTRACTION_SYSTEM_PROMPT, context)},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]


def build_vision_extraction_prompt(
    schema: type[BaseModel],
    images_base64: list[str],
    context: str | None = None,
) -> list[dict]:
    field_desc = _schema_to_field_descriptions(schema)
    json_schema_str = json.dumps(schema.model_json_schema(), indent=2)
    example = _build_example_output(schema)

    content_parts: list[dict] = []
    content_parts.append({
        "type": "text",
        "text": (
            f"## Schema Fields\n{field_desc}\n\n"
            f"## JSON Schema\n```json\n{json_schema_str}\n```\n\n"
            f"## Expected Output Format\n```json\n{example}\n```\n\n"
            f"The following are the {len(images_base64)} page(s) of the document. "
            "Extract the data according to the schema. "
            "Return ONLY the JSON object with 'data' and 'evidence' keys."
        ),
    })

    for _i, img_b64 in enumerate(images_base64):
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    return [
        {"role": "system", "content": _build_system_prompt(VISION_EXTRACTION_SYSTEM_PROMPT, context)},
        {"role": "user", "content": content_parts},
    ]
