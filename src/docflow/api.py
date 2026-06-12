from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from docflow._sync import run_sync
from docflow.extraction.models import ExtractionResult
from docflow.processor import DocumentPipeline


async def extract(
    path: str,
    schema: type[BaseModel],
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult:
    """Extract structured data from a document using one function call."""
    pipeline = DocumentPipeline(
        parser=parser,
        model=model,
        storage=storage,
        privacy=privacy,
        **kwargs,
    )
    return await pipeline.run(path, schema)


def extract_sync(
    path: str,
    schema: type[BaseModel],
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult:
    """Synchronous version of extract()."""
    return run_sync(
        extract(
            path, schema, model=model, parser=parser, storage=storage, privacy=privacy, **kwargs
        )
    )
