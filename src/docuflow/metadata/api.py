from __future__ import annotations

import asyncio
from pathlib import Path

from docuflow.metadata.models import DocumentMetadataResult


async def extract_metadata_async(path: str | Path) -> DocumentMetadataResult:
    """Extract document-level metadata without touching the main text layer.

    Dispatches on file extension: ``.docx`` uses the DOCX extractor, everything
    else uses the PDF extractor. Legacy ``.doc`` (binary Word) is not supported.

    The underlying extractors do blocking file I/O and parsing, so they run in a
    worker thread to avoid stalling the event loop.

    Args:
        path: PDF or DOCX file path.

    Returns:
        DocumentMetadataResult: Metadata objects found in the document.
    """
    suffix = Path(path).suffix.lower()

    if suffix == ".doc":
        result = DocumentMetadataResult(input_path=str(path))
        result.errors.append(
            "Legacy .doc (binary Word) is not supported for metadata extraction. "
            "Convert the file to .docx or PDF first."
        )
        return result

    if suffix == ".docx":
        from docuflow.metadata.docx_extractor import extract_docx_metadata
        return await asyncio.to_thread(extract_docx_metadata, path)

    from docuflow.metadata.pdf_extractor import extract_pdf_metadata
    return await asyncio.to_thread(extract_pdf_metadata, path)


def extract_metadata(path: str | Path) -> DocumentMetadataResult:
    """Synchronous wrapper for :func:`extract_metadata_async`.

    Args:
        path: PDF or DOCX file path.

    Returns:
        DocumentMetadataResult: Metadata objects found in the document.
    """
    from docuflow._sync import run_sync
    return run_sync(extract_metadata_async(path))
