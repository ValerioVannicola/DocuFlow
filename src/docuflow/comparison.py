from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from docuflow._sync import run_sync
from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import ExtractionResult


class ComparisonCell(BaseModel):
    document_id: str
    file_name: str
    value: Any = None
    confidence: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)


class FieldDifference(BaseModel):
    field_name: str
    all_agree: bool = True
    unique_values: list[Any] = Field(default_factory=list)
    value_counts: dict[str, int] = Field(default_factory=dict)
    summary: str = ""


class ComparisonResult(BaseModel):
    schema_name: str
    documents: list[str] = Field(default_factory=list)
    fields: dict[str, list[ComparisonCell]] = Field(default_factory=dict)
    differences: dict[str, FieldDifference] = Field(default_factory=dict)
    results: list[ExtractionResult] = Field(default_factory=list)


def _compute_difference(
    field_name: str, cells: list[ComparisonCell],
) -> FieldDifference:
    values = [c.value for c in cells]
    str_values = [str(v) for v in values]
    counts = Counter(str_values)
    unique = list(dict.fromkeys(values))
    n = len(cells)

    if len(counts) <= 1:
        summary = f"All {n} documents agree: {values[0]}"
        all_agree = True
    else:
        parts = []
        for val_str, count in counts.most_common():
            original = next(v for v in values if str(v) == val_str)
            parts.append(f"{count}/{n} say {original!r}")
        summary = ", ".join(parts)
        all_agree = False

    return FieldDifference(
        field_name=field_name,
        all_agree=all_agree,
        unique_values=unique,
        value_counts=dict(counts),
        summary=summary,
    )


async def compare_documents(
    files: list[str],
    schema: type[BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> ComparisonResult:
    semaphore = asyncio.Semaphore(concurrency)

    async def _extract(path: str) -> ExtractionResult:
        async with semaphore:
            return await pipeline.run(path, schema)

    tasks = [_extract(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    extraction_results: list[ExtractionResult] = []
    file_names: list[str] = []
    for path, result in zip(files, results, strict=False):
        if isinstance(result, Exception):
            continue
        extraction_results.append(result)
        name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        file_names.append(name)

    all_field_names: list[str] = []
    seen: set[str] = set()
    for r in extraction_results:
        for fname in r.fields:
            if fname not in seen:
                all_field_names.append(fname)
                seen.add(fname)

    fields: dict[str, list[ComparisonCell]] = {}
    for fname in all_field_names:
        cells: list[ComparisonCell] = []
        for r, file_name in zip(extraction_results, file_names, strict=False):
            field = r.fields.get(fname)
            if field:
                cells.append(ComparisonCell(
                    document_id=r.document_id,
                    file_name=file_name,
                    value=field.value,
                    confidence=field.confidence,
                    evidence=field.evidence,
                ))
            else:
                cells.append(ComparisonCell(
                    document_id=r.document_id,
                    file_name=file_name,
                ))
        fields[fname] = cells

    differences: dict[str, FieldDifference] = {}
    for fname, cells in fields.items():
        differences[fname] = _compute_difference(fname, cells)

    return ComparisonResult(
        schema_name=schema.__name__,
        documents=file_names,
        fields=fields,
        differences=differences,
        results=extraction_results,
    )


def compare_documents_sync(
    files: list[str],
    schema: type[BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> ComparisonResult:
    return run_sync(compare_documents(files, schema, pipeline, concurrency))
