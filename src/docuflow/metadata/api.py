from __future__ import annotations

from pathlib import Path

from docuflow.metadata.models import DocumentMetadataResult


async def extract_metadata_async(path: str | Path) -> DocumentMetadataResult:
    """Extract document-level metadata without touching the main text layer.

    Args:
        path: PDF or DOCX file path.

    Returns:
        DocumentMetadataResult: Metadata objects found in the document.
    """
    suffix = Path(path).suffix.lower()
    if suffix in (".docx", ".doc"):
        from docuflow.metadata.docx_extractor import extract_docx_metadata
        return extract_docx_metadata(path)
    else:
        from docuflow.metadata.pdf_extractor import extract_pdf_metadata
        return extract_pdf_metadata(path)


def extract_metadata(path: str | Path) -> DocumentMetadataResult:
    """Synchronous wrapper for :func:`extract_metadata_async`.

    Args:
        path: PDF or DOCX file path.

    Returns:
        DocumentMetadataResult: Metadata objects found in the document.
    """
    from docuflow._sync import run_sync
    return run_sync(extract_metadata_async(path))
