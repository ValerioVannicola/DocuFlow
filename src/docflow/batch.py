from __future__ import annotations

import asyncio
import csv
import io
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from docflow._sync import run_sync
from docflow.extraction.models import ExtractionResult, TokenUsage


class DocumentSummary(BaseModel):
    file_path: str
    file_name: str
    document_id: str = ""
    success: bool = True
    error: str = ""
    confidence: float = 0.0
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)


class BatchReport(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    needs_review: int = 0
    approved: int = 0
    average_confidence: float = 0.0
    usage: TokenUsage | None = None
    top_review_reasons: dict[str, int] = Field(default_factory=dict)
    field_names: list[str] = Field(default_factory=list)
    documents: list[DocumentSummary] = Field(default_factory=list)
    results: list[ExtractionResult] = Field(default_factory=list)

    def to_csv(self) -> str:
        if not self.documents:
            return ""

        output = io.StringIO()
        all_fields = self.field_names
        headers = ["file_name", "success", "confidence", "needs_review", *all_fields]
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()

        for doc_summary in self.documents:
            row: dict[str, Any] = {
                "file_name": doc_summary.file_name,
                "success": doc_summary.success,
                "confidence": round(doc_summary.confidence, 3),
                "needs_review": doc_summary.needs_review,
            }
            for field_name in all_fields:
                row[field_name] = doc_summary.data.get(field_name, "")
            writer.writerow(row)

        return output.getvalue()

    def to_dataframe(self) -> Any:
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "pandas is required for DataFrame export. "
                "Install with: pip install pandas"
            ) from e

        rows = []
        for doc_summary in self.documents:
            row = {
                "file_name": doc_summary.file_name,
                "document_id": doc_summary.document_id,
                "success": doc_summary.success,
                "confidence": doc_summary.confidence,
                "needs_review": doc_summary.needs_review,
                "error": doc_summary.error,
            }
            for field_name in self.field_names:
                row[field_name] = doc_summary.data.get(field_name)
            rows.append(row)

        return pd.DataFrame(rows)


async def process_batch(
    files: list[str],
    schema: type[BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> BatchReport:
    semaphore = asyncio.Semaphore(concurrency)
    summaries: list[DocumentSummary] = []
    results: list[ExtractionResult] = []
    all_field_names: list[str] = []
    seen_fields: set[str] = set()

    async def _process(path: str) -> None:
        name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        async with semaphore:
            try:
                result = await pipeline.run(path, schema)
                results.append(result)

                for fname in result.fields:
                    if fname not in seen_fields:
                        all_field_names.append(fname)
                        seen_fields.add(fname)

                summaries.append(DocumentSummary(
                    file_path=path,
                    file_name=name,
                    document_id=result.document_id,
                    success=True,
                    confidence=result.confidence,
                    needs_review=result.needs_review,
                    review_reasons=result.review_reasons,
                    data=result.data,
                ))
            except Exception as exc:
                summaries.append(DocumentSummary(
                    file_path=path,
                    file_name=name,
                    success=False,
                    error=str(exc),
                ))

    tasks = [_process(f) for f in files]
    await asyncio.gather(*tasks)

    succeeded = [s for s in summaries if s.success]
    failed = [s for s in summaries if not s.success]
    review_needed = [s for s in succeeded if s.needs_review]

    avg_conf = (
        sum(s.confidence for s in succeeded) / len(succeeded)
        if succeeded else 0.0
    )

    reason_counter: Counter[str] = Counter()
    for s in review_needed:
        for reason in s.review_reasons:
            reason_counter[reason] += 1

    total_usage: TokenUsage | None = None
    for r in results:
        if r.usage is not None:
            total_usage = (total_usage or TokenUsage()).combined(r.usage)

    return BatchReport(
        total=len(files),
        succeeded=len(succeeded),
        failed=len(failed),
        needs_review=len(review_needed),
        approved=len([s for s in succeeded if not s.needs_review]),
        average_confidence=avg_conf,
        usage=total_usage,
        top_review_reasons=dict(reason_counter.most_common(10)),
        field_names=all_field_names,
        documents=summaries,
        results=results,
    )


def process_batch_sync(
    files: list[str],
    schema: type[BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> BatchReport:
    return run_sync(process_batch(files, schema, pipeline, concurrency))
