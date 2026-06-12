from __future__ import annotations

import math

from pydantic import BaseModel, create_model

from docuflow.extraction.models import ExtractionResult, TokenUsage


def shard_schema(schema: type[BaseModel], n_shards: int) -> list[type[BaseModel]]:
    """Split a schema into up to n_shards partial schemas with contiguous
    field groups (adjacent fields tend to be related — totals next to
    subtotals — so contiguous beats round-robin for extraction coherence).

    Field types, descriptions, defaults and required-ness are preserved.
    Returns [schema] unchanged when sharding wouldn't help.
    """
    names = list(schema.model_fields.keys())
    if n_shards <= 1 or len(names) < 2:
        return [schema]

    n_shards = min(n_shards, len(names))
    size = math.ceil(len(names) / n_shards)
    shards: list[type[BaseModel]] = []
    for i in range(0, len(names), size):
        chunk = names[i : i + size]
        fields = {
            name: (schema.model_fields[name].annotation, schema.model_fields[name])
            for name in chunk
        }
        shards.append(
            create_model(f"{schema.__name__}Shard{len(shards) + 1}", **fields)
        )
    return shards


def merge_shard_results(
    results: list[ExtractionResult], schema: type[BaseModel],
) -> ExtractionResult:
    """Combine per-shard extraction results into one result for the full
    schema. Fields/data union; usage sums; confidence recomputed over all
    fields; document-level OCR is identical across shards (same document)."""
    base = results[0]
    merged = ExtractionResult(
        document_id=base.document_id,
        schema_name=schema.__name__,
        trace_id=base.trace_id,
        model_name=base.model_name,
        parser_name=base.parser_name,
        ocr=next((r.ocr for r in results if r.ocr is not None), None),
    )

    usage: TokenUsage | None = None
    for r in results:
        merged.data.update(r.data)
        merged.fields.update(r.fields)
        merged.validation_errors.extend(r.validation_errors)
        if r.usage is not None:
            usage = (usage or TokenUsage()).combined(r.usage)
    merged.usage = usage

    if merged.fields:
        merged.confidence = sum(
            f.confidence for f in merged.fields.values()
        ) / len(merged.fields)
    return merged
