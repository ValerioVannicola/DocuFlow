"""DocuFlow MCP Server — expose DocuFlow as tools for AI agents.

Run with:
    uv run python -m docuflow.mcp_server
    # or
    mcp run docuflow.mcp_server
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "DocuFlow",
    instructions="Extract structured data from documents with evidence, validation, and review.",
)


@mcp.tool()
async def extract_document(
    file_path: str,
    schema_name: str = "invoice",
    parser: str = "auto",
    model: str = "openai/gpt-4o",
    extraction_mode: str = "single",
    n_instances: int = 5,
    context: str = "",
) -> str:
    """Extract structured data from a document using a schema.

    Args:
        file_path: Path to the document file
        schema_name: Template name (invoice, contract, receipt) or Python dotted path
        parser: Parser to use (auto, pdfplumber, tesseract, docling, smart, markitdown, azure-di, textract, google-docai)
        model: LLM model (openai/gpt-4o, anthropic/claude-sonnet-4-20250514, etc)
        extraction_mode: single (1 call) or multi (N calls + decider)
        n_instances: Number of parallel agents for multi mode
        context: Domain context for the LLM (e.g. "You work in insurance")

    Returns:
        JSON with extracted data, per-field evidence, trust gates, OCR confidence
        score, and consensus score
    """
    from docuflow.cli.utils import load_schema
    from docuflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(
        parser=parser,
        model=model,
        extraction_mode=extraction_mode,
        n_instances=n_instances,
        context=context or None,
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
) -> str:
    """Extract data by sending page images directly to a vision LLM. No parser needed.

    Best for: complex layouts, forms, scanned documents with visual elements.

    Args:
        file_path: Path to the PDF file
        schema_name: Template name or Python dotted path
        model: Vision-capable LLM model
        extraction_mode: single or multi
        n_instances: Number of parallel agents for multi mode

    Returns:
        JSON with extracted data, evidence, and trust scores
    """
    from docuflow.cli.utils import load_schema
    from docuflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(
        parser=None,
        extraction_type="vision",
        model=model,
        extraction_mode=extraction_mode,
        n_instances=n_instances,
    )
    result = await pipeline.run(file_path, schema)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def discover_schema(
    file_path: str,
    parser: str = "auto",
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
    from docuflow.discover import discover_schema as _discover

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
    parser: str = "auto",
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
    from docuflow.cli.utils import load_schema
    from docuflow.comparison import compare_documents as _compare
    from docuflow.processor import DocumentPipeline

    schema = load_schema(schema_name)
    pipeline = DocumentPipeline(parser=parser, model=model)
    result = await _compare(file_paths, schema, pipeline)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def process_batch(
    folder_path: str,
    schema_name: str = "invoice",
    parser: str = "auto",
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
        JSON with total/succeeded/failed counts, legacy average trust-gate rate,
        top review reasons, and per-document results
    """
    from pathlib import Path

    from docuflow.batch import process_batch as _batch
    from docuflow.cli.utils import load_schema
    from docuflow.processor import DocumentPipeline

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
    from docuflow.templates.registry import list_templates as _list

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
    from docuflow.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    import yaml

    data = registry.load_raw(name)
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


@mcp.tool()
async def search_in_document(
    file_path: str,
    query: str,
    parser: str = "auto",
) -> str:
    """Search for text in a document with page and bounding box locations.

    Args:
        file_path: Path to the PDF file
        query: Text to search for (case-insensitive)
        parser: Parser to use for reading the document

    Returns:
        JSON with hits including page number, bounding box, and context
    """
    from pathlib import Path

    from docuflow.ingestion.local import ingest_file
    from docuflow.ingestion.mime import detect_source_kind
    from docuflow.processor import DocumentPipeline
    from docuflow.search import search_document

    doc = await ingest_file(file_path)

    source_kind = detect_source_kind(Path(file_path))
    parser_obj = DocumentPipeline(parser=parser)._resolve_parser_for_source(source_kind)
    if parser_obj is not None:
        doc = await parser_obj.parse(doc)

    result = search_document(doc, query)
    return result.model_dump_json(indent=2)


@mcp.tool()
async def get_pending_reviews(
    store_path: str = "./.docuflow_store",
) -> str:
    """Get document IDs that need human review.

    Args:
        store_path: Path to the local document store

    Returns:
        JSON list of document IDs pending review
    """
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    ids = await store.get_pending_reviews()
    return json.dumps(ids, indent=2)


@mcp.tool()
async def get_extraction_result(
    document_id: str,
    store_path: str = "./.docuflow_store",
) -> str:
    """Load a stored extraction result by document ID.

    Args:
        document_id: The document UUID
        store_path: Path to the local document store

    Returns:
        JSON extraction result with fields, evidence, trust, and review status
    """
    from docuflow.storage.local import LocalDocumentStore

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
    store_path: str = "./.docuflow_store",
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
    from docuflow.storage.local import LocalDocumentStore

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
    store_path: str = "./.docuflow_store",
) -> str:
    """Approve a reviewed document.

    Args:
        document_id: The document UUID
        approved_by: Who approved it
        store_path: Path to the local document store

    Returns:
        JSON confirmation with review status
    """
    from docuflow.storage.local import LocalDocumentStore

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
    store_path: str = "./.docuflow_store",
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
    from docuflow.storage.local import LocalDocumentStore

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
async def get_pending_fills(
    store_path: str = "./.docuflow_store",
) -> str:
    """Get document IDs whose PDF form fill awaits human review before being written.

    Args:
        store_path: Path to the local document store

    Returns:
        JSON list of document IDs with a pending, review-flagged fill
    """
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    ids = await store.get_pending_fills()
    return json.dumps(ids, indent=2)


@mcp.tool()
async def edit_fill_field(
    document_id: str,
    field_name: str,
    new_value: str,
    corrected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str:
    """Change a planned fill value before the PDF is committed, and save it.

    Args:
        document_id: The document UUID
        field_name: Name of the field to edit
        new_value: The corrected value to write
        corrected_by: Who made the edit
        reason: Why the edit was needed
        store_path: Path to the local document store

    Returns:
        JSON with the field's old value, new value, and correction record
    """
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_filling_result(document_id)
    if result is None:
        return json.dumps({"error": f"No filling result found for document {document_id}"})

    result.edit_field(field_name, value=new_value, corrected_by=corrected_by, reason=reason)
    await store.save_filling_result(result)

    field = result.fields[field_name]
    return json.dumps({
        "field_name": field_name,
        "old_value": field.original_value,
        "new_value": field.value,
        "corrected": True,
        "corrected_by": corrected_by,
    }, indent=2, default=str)


@mcp.tool()
async def approve_fill(
    document_id: str,
    approved_by: str = "",
    commit: bool = True,
    store_path: str = "./.docuflow_store",
) -> str:
    """Approve a reviewed PDF fill and (by default) write the output PDF.

    Args:
        document_id: The document UUID
        approved_by: Who approved it
        commit: When True, write the output PDF immediately after approval
        store_path: Path to the local document store

    Returns:
        JSON confirmation with review status, committed flag, and output path
    """
    from docuflow.filling.api import commit_fill_async
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_filling_result(document_id)
    if result is None:
        return json.dumps({"error": f"No filling result found for document {document_id}"})

    result.approve(approved_by=approved_by)
    if commit:
        await commit_fill_async(result)
    await store.save_filling_result(result)

    return json.dumps({
        "document_id": document_id,
        "review_status": result.review_status,
        "approved_by": approved_by,
        "committed": result.committed,
        "output_path": result.output_path if result.committed else "",
    }, indent=2)


@mcp.tool()
async def reject_fill(
    document_id: str,
    rejected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str:
    """Reject a reviewed PDF fill; the output PDF is not written.

    Args:
        document_id: The document UUID
        rejected_by: Who rejected it
        reason: Why it was rejected
        store_path: Path to the local document store

    Returns:
        JSON confirmation with review status and reason
    """
    from docuflow.storage.local import LocalDocumentStore

    store = LocalDocumentStore(store_path)
    result = await store.load_filling_result(document_id)
    if result is None:
        return json.dumps({"error": f"No filling result found for document {document_id}"})

    result.reject(rejected_by=rejected_by, reason=reason)
    await store.save_filling_result(result)

    return json.dumps({
        "document_id": document_id,
        "review_status": result.review_status,
        "rejected_by": rejected_by,
        "reason": reason,
    }, indent=2)


@mcp.tool()
async def split_document(
    file_path: str,
    sections: str,
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: str = "",
) -> str:
    """Split a PDF into named sections by assigning page numbers using an LLM.

    Args:
        file_path: Path to the PDF document
        sections: JSON array of section objects, each with "name" and "description".
            Example: [{"name": "body", "description": "Main contract terms"},
                      {"name": "exhibits", "description": "Exhibit attachments"}]
        model: LiteLLM model string
        deep: When True, also return confidence and evidence per section
        allow_overlap: When True, a page may appear in multiple sections
        split_rules: Optional freeform instruction overriding the default splitting logic
        pages: Comma-separated 0-based page indices to process; empty means all pages

    Returns:
        SplitResult JSON with page_map (section → pages), confidence, evidence, usage
    """
    from docuflow.splitting.api import split_document_async as _split
    from docuflow.splitting.models import DocumentSection

    try:
        raw_sections = json.loads(sections)
        doc_sections = [DocumentSection(**s) for s in raw_sections]
    except Exception as exc:
        return json.dumps({"error": f"Invalid sections JSON: {exc}"})

    page_list: list[int] | None = None
    if pages.strip():
        try:
            page_list = [int(p.strip()) for p in pages.split(",") if p.strip()]
        except ValueError:
            return json.dumps({"error": "pages must be comma-separated integers"})

    result = await _split(
        file_path,
        doc_sections,
        model=model,
        deep=deep,
        allow_overlap=allow_overlap,
        split_rules=split_rules,
        pages=page_list,
    )

    return json.dumps({
        "success": result.success,
        "total_pages": result.total_pages,
        "page_map": result.page_map,
        "sections": {
            name: {
                "pages": sr.pages,
                "confidence": sr.confidence,
                "evidence": sr.evidence,
            }
            for name, sr in result.sections.items()
        },
        "usage": result.usage,
        "warnings": result.warnings,
        "errors": result.errors,
    }, indent=2)


@mcp.tool()
async def fill_docx_form(
    file_path: str,
    data: str,
    output_path: str = "",
    strategy: str = "auto",
    flatten: bool = False,
    review: bool = False,
    document_id: str = "",
    store_path: str = "./.docuflow_store",
) -> str:
    """Fill a DOCX form (content controls) with structured data.

    Args:
        file_path: Path to the input .docx file
        data: JSON string of field values to fill (keys match content control tags or aliases)
        output_path: Where to save the filled DOCX; defaults to <stem>-filled.docx
        strategy: "auto" (detect) or "content_controls" (Word SDT fields)
        flatten: Remove SDT wrappers after filling (content_controls only)
        review: When True, plan the fill but do not write the file yet
        document_id: Optional document identifier for storage
        store_path: Path to the local document store (used when review=True)

    Returns:
        FillingResult JSON (success, strategy, fields, warnings, errors, review_status)
    """
    import json as _json

    from docuflow.filling.api import fill_docx_form_async as _fill_docx_form_async

    try:
        data_dict = _json.loads(data)
    except Exception as exc:
        return json.dumps({"error": f"Invalid JSON data: {exc}"})

    result = await _fill_docx_form_async(
        file_path,
        data_dict,
        output_path=output_path or None,
        document_id=document_id,
        review=review,
        strategy=strategy,  # type: ignore[arg-type]
        flatten=flatten,
    )

    if review and document_id:
        from docuflow.storage.local import LocalDocumentStore

        store = LocalDocumentStore(store_path)
        await store.save_filling_result(result)

    return json.dumps({
        "success": result.success,
        "strategy": result.strategy,
        "output_path": result.output_path,
        "committed": result.committed,
        "review_status": result.review_status if review else None,
        "fields": {
            name: {"value": str(f.value), "target": f.target_name, "method": f.method}
            for name, f in result.fields.items()
        },
        "unmapped_model_fields": result.unmapped_model_fields,
        "unmapped_doc_fields": result.unmapped_pdf_fields,
        "warnings": result.warnings,
        "errors": result.errors,
    }, indent=2)


@mcp.tool()
async def extract_document_metadata(
    file_path: str,
) -> str:
    """Extract document-level metadata: comments, highlights, hyperlinks, signatures, and tracked changes.

    Works on PDF and DOCX files. PDF extracts annotation-layer objects (comments, highlights,
    hyperlinks, signature fields). DOCX extracts comments, tracked insertions/deletions,
    hyperlinks, and highlighted runs.

    Args:
        file_path: Path to the PDF or DOCX file

    Returns:
        DocumentMetadataResult JSON with comments, highlights, hyperlinks, signatures,
        revisions, warnings, and errors
    """
    from docuflow.metadata.api import extract_metadata_async

    result = await extract_metadata_async(file_path)

    def _bbox(b) -> dict | None:
        if b is None:
            return None
        return {"x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1}

    return json.dumps({
        "success": result.success,
        "has_metadata": result.has_metadata,
        "comments": [
            {
                "page_number": c.page_number,
                "author": c.author,
                "date": c.date,
                "text": c.text,
                "bbox": _bbox(c.bbox),
            }
            for c in result.comments
        ],
        "highlights": [
            {
                "page_number": h.page_number,
                "subtype": h.subtype,
                "color": h.color,
                "text": h.text,
                "bbox": _bbox(h.bbox),
            }
            for h in result.highlights
        ],
        "hyperlinks": [
            {
                "page_number": lnk.page_number,
                "url": lnk.url,
                "text": lnk.text,
                "bbox": _bbox(lnk.bbox),
            }
            for lnk in result.hyperlinks
        ],
        "signatures": [
            {
                "page_number": s.page_number,
                "field_name": s.field_name,
                "signer": s.signer,
                "date": s.date,
                "signed": s.signed,
                "bbox": _bbox(s.bbox),
            }
            for s in result.signatures
        ],
        "revisions": [
            {
                "revision_type": r.revision_type,
                "author": r.author,
                "date": r.date,
                "text": r.text,
            }
            for r in result.revisions
        ],
        "warnings": result.warnings,
        "errors": result.errors,
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
    from docuflow.screenshots import screenshot_pages

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
