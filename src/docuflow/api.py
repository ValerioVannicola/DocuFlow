from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from docuflow._sync import run_sync
from docuflow.extraction.models import ExtractionResult
from docuflow.processor import DocumentPipeline


async def extract(
    path: str,
    schema: type[BaseModel],
    model: str = "openai/gpt-4o",
    parser: str = "auto",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult:
    """Extract structured data from a document using one function call.

    Args:
        path: Input document path.
        schema: Pydantic schema describing the fields to extract.
        model: LLM model name passed to LiteLLM.
        parser: Parser selector. ``auto`` uses source-aware defaults.
        storage: Optional storage backend name or instance.
        privacy: Optional privacy policy configuration.
        **kwargs: Extra :class:`~docuflow.processor.DocumentPipeline` options.

    Returns:
        ExtractionResult: Final extracted result.
    """
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
    parser: str = "auto",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult:
    """Synchronous version of :func:`extract`.

    Args:
        path: Input document path.
        schema: Pydantic schema describing the fields to extract.
        model: LLM model name passed to LiteLLM.
        parser: Parser selector. ``auto`` uses source-aware defaults.
        storage: Optional storage backend name or instance.
        privacy: Optional privacy policy configuration.
        **kwargs: Extra :class:`~docuflow.processor.DocumentPipeline` options.

    Returns:
        ExtractionResult: Final extracted result.
    """
    return run_sync(
        extract(
            path, schema, model=model, parser=parser, storage=storage, privacy=privacy, **kwargs
        )
    )
