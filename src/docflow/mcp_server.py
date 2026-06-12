"""DocFlow MCP Server — expose DocFlow as tools for AI agents.

Run with:
    uv run python -m docflow.mcp_server
    # or
    mcp run docflow.mcp_server
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "DocFlow",
    instructions="Extract structured data from documents with evidence, validation, and review.",
)


@mcp.tool()
async def extract_document(
    file_path: str,
    schema_name: str = "invoice",
    parser: str = "pdfplumber",
    model: str = "openai/gpt-4o",
    extraction_mode: str = "single",
    n_instances: int = 5,
    context: str = "",
    scoring: str = "qualitative",
) -> str:
    """Extract structured data from a document using a schema.

    Args:
        file_path: Path to the PDF file
        schema_name: Template name (invoice, contract, receipt) or Python dotted path
        parser: Parser to use (pdfplumber, tesseract, docling, smart, azure-di, textract, google-docai)
        model: LLM model (openai/gpt-4o, anthropic/claude-sonnet-4-20250514, etc)
        extraction_mode: single (1 call) or multi (N calls + decider)
        n_instances: Number of parallel agents for multi mode
        context: Domain context for the LLM (e.g. "You work in insurance")
        scoring: qualitative (binary skip/review) or quantitative (percentage)

    Returns:
        JSON with extracted data, per-field evidence, trust scores, and confidence
    """
    from docflow.cli.utils import load_schema
    from docflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(
        parser=parser,
        model=model,
        extraction_mode=extraction_mode,
        n_instances=n_instances,
        context=context or None,
        scoring=scoring,
    )
    result = await pipeline.run(file_path, schema)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def extract_with_vision(
    file_path: str,
    schema_name: str = "invoice",
    model: str = "openai/gpt-4o",
    extraction_mode: str = "single",
    n_instances: int = 5,
    scoring: str = "qualitative",
) -> str:
    """Extract data by sending page images directly to a vision LLM. No parser needed.

    Best for: complex layouts, forms, scanned documents with visual elements.

    Args:
        file_path: Path to the PDF file
        schema_name: Template name or Python dotted path
        model: Vision-capable LLM model
        extraction_mode: single or multi
        n_instances: Number of parallel agents for multi mode
        scoring: qualitative or quantitative

    Returns:
        JSON with extracted data, evidence, and trust scores
    """
    from docflow.cli.utils import load_schema
    from docflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(
        parser=None,
        extraction_type="vision",
        model=model,
        extraction_mode=extraction_mode,
        n_instances=n_instances,
        scoring=scoring,
    )
    result = await pipeline.run(file_path, schema)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def discover_schema(
    file_path: str,
    parser: str = "pdfplumber",
    model: str = "openai/gpt-4o",
) -> str:
    """Analyze a document and auto-generate an extraction schema.

    The LLM reads the document and identifies all extractable fields.
    Returns the suggested schema as both a field list and a YAML template.

    Args:
        file_path: Path to the document
        parser: Parser to use for reading the document
        model: LLM model for analysis

    Returns:
        JSON with document_type, description, fields, and yaml_template
    """
    from docflow.discover import discover_schema as _discover

    result = await _discover(file_path, model=model, parser=parser)
    return json.dumps({
        "document_type": result.document_type,
        "description": result.description,
        "fields": [f.model_dump() for f in result.fields],
        "yaml_template": result.yaml_template,
    }, indent=2)


@mcp.tool()
async def compare_documents(
    file_paths: list[str],
    schema_name: str = "invoice",
    parser: str = "pdfplumber",
    model: str = "openai/gpt-4o",
) -> str:
    """Compare extracted fields across multiple documents.

    Extracts the same schema from each document and shows field-by-field
    differences with evidence.

    Args:
        file_paths: List of paths to PDF files
        schema_name: Template name or Python dotted path
        parser: Parser to use
        model: LLM model

    Returns:
        JSON with per-field comparison, differences, and agreement summary
    """
    from docflow.cli.utils import load_schema
    from docflow.comparison import compare_documents as _compare
    from docflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(parser=parser, model=model)
    result = await _compare(file_paths, schema, pipeline)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def process_batch(
    folder_path: str,
    schema_name: str = "invoice",
    parser: str = "pdfplumber",
    model: str = "openai/gpt-4o",
    pattern: str = "**/*.pdf",
    concurrency: int = 5,
) -> str:
    """Process all documents in a folder and get a summary report.

    Args:
        folder_path: Path to folder containing documents
        schema_name: Template name or Python dotted path
        parser: Parser to use
        model: LLM model
        pattern: File glob pattern (default: **/*.pdf)
        concurrency: Max parallel extractions

    Returns:
        JSON with total/succeeded/failed counts, average confidence,
        top review reasons, and per-document results
    """
    from pathlib import Path

    from docflow.batch import process_batch as _batch
    from docflow.cli.utils import load_schema
    from docflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    folder = Path(folder_path)
    files = sorted(str(p) for p in folder.glob(pattern) if p.is_file())

    pipeline = DocumentPipeline(parser=parser, model=model)
    report = await _batch(files, schema, pipeline, concurrency=concurrency)

    return json.dumps({
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "needs_review": report.needs_review,
        "approved": report.approved,
        "average_confidence": report.average_confidence,
        "top_review_reasons": report.top_review_reasons,
        "documents": [d.model_dump() for d in report.documents],
    }, indent=2, default=str)


@mcp.tool()
async def list_templates() -> str:
    """List all available extraction templates (built-in and custom).

    Returns:
        JSON list of templates with name, version, source, and description
    """
    from docflow.templates.registry import list_templates as _list

    templates = _list()
    return json.dumps(
        [{"name": t.name, "version": t.version, "source": t.source, "description": t.description}
         for t in templates],
        indent=2,
    )


@mcp.tool()
async def show_template(name: str) -> str:
    """Show the YAML definition of a template.

    Args:
        name: Template name (e.g. invoice, contract, receipt)

    Returns:
        YAML template content
    """
    from docflow.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    import yaml

    data = registry.load_raw(name)
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


@mcp.tool()
async def search_in_document(
    file_path: str,
    query: str,
    parser: str = "pdfplumber",
) -> str:
    """Search for text in a document with page and bounding box locations.

    Args:
        file_path: Path to the PDF file
        query: Text to search for (case-insensitive)
        parser: Parser to use for reading the document

    Returns:
        JSON with hits including page number, bounding box, and context
    """
    from docflow.ingestion.local import ingest_file
    from docflow.search import search_document

    doc = await ingest_file(file_path)

    if parser == "pdfplumber":
        from docflow.parsing.pdfplumber_parser import PdfplumberParser
        doc = await PdfplumberParser().parse(doc)
    elif parser == "tesseract":
        from docflow.parsing.tesseract_parser import TesseractParser
        doc = await TesseractParser().parse(doc)
    elif parser == "docling":
        from docflow.parsing.docling_parser import DoclingParser
        doc = await DoclingParser().parse(doc)
    elif parser == "smart":
        from docflow.parsing.smart_parser import SmartParser
        doc = await SmartParser().parse(doc)

    result = search_document(doc, query)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def get_pending_reviews(
    store_path: str = "./.docflow_store",
) -> str:
    """Get document IDs that need human review.

    Args:
        store_path: Path to the local document store

    Returns:
        JSON list of document IDs pending review
    """
    from docflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    ids = await store.get_pending_reviews()
    return json.dumps(ids, indent=2)


@mcp.tool()
async def get_extraction_result(
    document_id: str,
    store_path: str = "./.docflow_store",
) -> str:
    """Load a stored extraction result by document ID.

    Args:
        document_id: The document UUID
        store_path: Path to the local document store

    Returns:
        JSON extraction result with fields, evidence, trust, and review status
    """
    from docflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_result(document_id)
    if result is None:
        return json.dumps({"error": f"No result found for document {document_id}"})
    return result.model_dump_json(indent=2)


@mcp.tool()
async def correct_field(
    document_id: str,
    field_name: str,
    new_value: str,
    corrected_by: str = "",
    reason: str = "",
    store_path: str = "./.docflow_store",
) -> str:
    """Correct an extracted field value and save the updated result.

    Args:
        document_id: The document UUID
        field_name: Name of the field to correct
        new_value: The correct value
        corrected_by: Who made the correction
        reason: Why the correction was needed
        store_path: Path to the local document store

    Returns:
        JSON with updated field showing old value, new value, and correction record
    """
    from docflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_result(document_id)
    if result is None:
        return json.dumps({"error": f"No result found for document {document_id}"})

    result.correct_field(field_name, new_value, corrected_by=corrected_by, reason=reason)
    await store.save_result(result)

    field = result.fields[field_name]
    return json.dumps({
        "field_name": field_name,
        "old_value": field.original_value,
        "new_value": field.value,
        "corrected": True,
        "corrected_by": corrected_by,
    }, indent=2, default=str)


@mcp.tool()
async def approve_document(
    document_id: str,
    approved_by: str = "",
    store_path: str = "./.docflow_store",
) -> str:
    """Approve a reviewed document.

    Args:
        document_id: The document UUID
        approved_by: Who approved it
        store_path: Path to the local document store

    Returns:
        JSON confirmation with review status
    """
    from docflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_result(document_id)
    if result is None:
        return json.dumps({"error": f"No result found for document {document_id}"})

    result.approve(approved_by=approved_by)
    await store.save_result(result)

    return json.dumps({
        "document_id": document_id,
        "review_status": result.review_status,
        "approved_by": approved_by,
    }, indent=2)


@mcp.tool()
async def reject_document(
    document_id: str,
    rejected_by: str = "",
    reason: str = "",
    store_path: str = "./.docflow_store",
) -> str:
    """Reject a reviewed document.

    Args:
        document_id: The document UUID
        rejected_by: Who rejected it
        reason: Why it was rejected
        store_path: Path to the local document store

    Returns:
        JSON confirmation with review status and reason
    """
    from docflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_result(document_id)
    if result is None:
        return json.dumps({"error": f"No result found for document {document_id}"})

    result.reject(rejected_by=rejected_by, reason=reason)
    await store.save_result(result)

    return json.dumps({
        "document_id": document_id,
        "review_status": result.review_status,
        "rejected_by": rejected_by,
        "reason": reason,
    }, indent=2)


@mcp.tool()
async def screenshot_document(
    file_path: str,
    output_dir: str,
    pages: str = "",
    dpi: int = 200,
) -> str:
    """Render document pages as PNG images.

    Args:
        file_path: Path to the PDF file
        output_dir: Directory to save screenshots
        pages: Comma-separated page numbers (empty = all pages)
        dpi: Rendering DPI

    Returns:
        JSON list of generated screenshots with dimensions and file paths
    """
    from docflow.screenshots import screenshot_pages

    page_list = [int(p.strip()) for p in pages.split(",") if p.strip()] or None
    results = await screenshot_pages(file_path, output_dir=output_dir, pages=page_list, dpi=dpi)
    return json.dumps(
        [{"page": r.page_number, "width": r.width, "height": r.height, "file": r.file_path}
         for r in results],
        indent=2,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
