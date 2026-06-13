# DocuFlow Technical Documentation

This directory is the full user-facing technical documentation for DocuFlow. The root-level
agent files (`AGENTS.md`, `CLAUDE.md`, `CODEX.md`, and similar integration notes) are quick
references for AI coding agents; they should point agents back to this `docs/` directory for
the complete public API, supported options, and examples.

## Documentation Map

- `technical-index.md` — installation extras, API conventions, and a map of the library.
- `extraction-pipeline-api.md` — `extract()`, `extract_async()`, `DocumentPipeline`, extraction
  types, extraction modes, scoring, escalation, verification, sharding, and LLM options.
- `workflow-configs-and-manual-pipelines.md` — YAML workflows, `WorkflowConfig`, `run_workflow()`,
  export helpers, `Pipeline`, and workflow steps.
- `schemas-templates-and-discovery.md` — Pydantic schemas, YAML templates, template registry,
  and LLM schema discovery.
- `parsers-ocr-rendering-and-search.md` — parser choices and constructor options, OCR behavior,
  coordinate conventions, screenshots, field highlights, text search, and text location.
- `results-and-data-models.md` — `ExtractionResult`, fields, evidence, confidence, trust,
  provenance, document/page/block/table models, and token usage.
- `validation-review-privacy-and-storage.md` — validators, review rules, LLM reviewers, privacy
  policy/anonymization, mapping stores, and local document storage.
- `batch-comparison-routing-quality-and-eval.md` — batch processing, document comparison, workflow
  routing, quality reports/logging, and evaluation harnesses.
- `serving-cli-mcp-and-deployment.md` — FastAPI serving, Docker generation, CLI commands, MCP
  tools, and deployment parameters.

## Installation Extras

DocuFlow requires Python 3.11 or newer.

```bash
pip install docuflow[all]
```

Install smaller extras when you only need part of the stack:

| Extra | Installs | Use when |
| --- | --- | --- |
| `pdf` | `pdfplumber`, `pypdfium2` | Native PDF text extraction and page rendering. |
| `ocr` | `pytesseract`, `Pillow` | Local OCR through Tesseract. Requires the system `tesseract` binary. |
| `llm` | `litellm` | LLM-backed extraction, review, schema discovery, routing. |
| `privacy` | Presidio analyzer/anonymizer | Text anonymization before LLM calls. |
| `docling` | Docling | Complex layouts and first-class table extraction. |
| `azure` | Azure Document Intelligence SDK | Cloud OCR with Azure Document Intelligence. |
| `aws` | `boto3` | Cloud OCR with AWS Textract. |
| `gcp` | Google Document AI SDK | Cloud OCR with Google Document AI. |
| `mcp` | MCP server dependencies | Expose DocuFlow as AI-agent tools. |
| `serve` | FastAPI, Uvicorn, multipart upload support | HTTP microservice deployment. |
| `dev` | pytest, ruff, reportlab | Local development and tests. |
| `all` | All runtime extras | Full feature set. |

Common combinations:

```bash
pip install docuflow[pdf,llm]
pip install docuflow[ocr,llm]
pip install docuflow[docling,llm]
pip install docuflow[serve]
pip install docuflow[mcp]
```

## Public API Conventions

Most high-level APIs have async and sync entry points:

| Sync API | Async API |
| --- | --- |
| `docuflow.extract()` | `docuflow.extract_async()` |
| `DocumentPipeline.run_sync()` | `DocumentPipeline.run()` |
| `run_workflow()` | `run_workflow_async()` |
| `process_batch()` | `process_batch_async()` |
| `compare_documents()` | `compare_documents_async()` |
| `discover_schema()` | `discover_schema_async()` |
| `screenshot_pages_sync()` | `screenshot_pages()` |
| `highlight_fields()` | `highlight_fields_async()` |

Internally, sync wrappers run the async implementation and return the same model types.

## Main Imports

```python
from docuflow import (
    DocumentPipeline,
    Pipeline,
    PrivacyPolicy,
    WorkflowRouter,
    compare_documents,
    discover_schema,
    extract,
    process_batch,
    quality_report,
    run_workflow,
)
```

Specialized imports are documented in the family-specific files. Important examples:

```python
from docuflow.templates import load_template, list_templates, TemplateRegistry
from docuflow.validation import RequiredFields, EvidenceRequired, TypeValidation, CustomRule
from docuflow.review import OverallConfidenceBelow, FieldConfidenceBelow, LLMReviewer
from docuflow.search import search_document
from docuflow.screenshots import screenshot_pages_sync
from docuflow.storage.local import LocalDocumentStore
from docuflow.workflow_config import WorkflowConfig, load_workflow_config
```

## Supported Top-Level Options

These are the most common selectable values across the high-level APIs.

| Family | Parameter | Supported values |
| --- | --- | --- |
| Parser | `parser` | `"pdfplumber"`, `"tesseract"`, `"docling"`, `"smart"`, `"azure-di"`, `"textract"`, `"google-docai"`, `"none"`/`None` for direct vision modes. |
| Extraction type | `extraction_type` | `"text"`, `"vision"`, `"hybrid"`, `"auto"`. |
| Extraction mode | `extraction_mode` / `mode` | `"single"`, `"multi"`. |
| Scoring | `scoring` | `"qualitative"`, `"quantitative"`. |
| Storage | `storage` | `None`, `"local"`, `{"type": "local", "path": "..."}`, or a storage object. |
| Privacy mode | `PrivacyPolicy.mode` | `"redact"`, `"mask"`, `"pseudonymize"`, `"hash"`. |
| Review status | `ExtractionResult.review_status` | `"pending"`, `"approved"`, `"rejected"`. |
| Local store query status | `LocalDocumentStore.get_by_status()` | `"pending_review"`, `"approved"`, `"rejected"`, `"pending"`. |
| Highlight color | `highlight_fields(color=...)` | `None`, `"auto"`, CSS color string, RGB tuple, RGBA tuple. |
| Screenshot/highlight format | `format` | Usually `"png"` or `"jpeg"`, depending on Pillow support. |

## Coordinate And Evidence Contract

DocuFlow normalizes document geometry into a page-local coordinate system:

- Origin is top-left.
- Native PDF, Tesseract, Textract, Azure PDF, Docling where possible: PDF points (`"pt"`, 72 per inch).
- Providers without reliable physical dimensions, such as some image-based cloud OCR outputs: pixels (`"px"`).
- `BoundingBox.to_relative(page.width, page.height)` converts any page-space rectangle to 0-1 coordinates.
- Multi-line and cross-page matches use `PageRect` lists, one rectangle per page/line segment.

Evidence and OCR spans use the same coordinate model, so search results, field evidence, OCR
confidence spans, screenshots, and highlight rendering are interoperable.

## Development Commands

From the repository root:

```bash
uv pip install -e ".[all,dev]"
uv run pytest -m "not integration"
uv run pytest
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## Environment Notes

LLM calls use LiteLLM model strings such as `openai/gpt-4o`, `anthropic/claude-sonnet-4-6`, or
`gemini/gemini-2.5-flash`. Configure provider API keys the way LiteLLM expects, or pass
`llm_kwargs={"api_key": "..."}` to `DocumentPipeline`.

Cloud OCR uses provider-native credentials:

- Azure: pass `endpoint`/`key`, or set `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` and
  `AZURE_DOCUMENT_INTELLIGENCE_KEY`.
- AWS Textract: standard `boto3` credential chain.
- Google Document AI: application default credentials plus `GOOGLE_DOCAI_PROJECT`,
  `GOOGLE_DOCAI_LOCATION`, and `GOOGLE_DOCAI_PROCESSOR_ID` unless passed explicitly.
