# DocFlow — Agent Integration Guide

This file tells AI coding agents everything they need to know to integrate DocFlow into a project.

## What DocFlow Does

DocFlow extracts structured data from documents (PDFs, scans, images) using LLMs. You define a Pydantic schema, point it at a document, and get back validated fields with evidence, confidence scores, and bounding boxes.

## Installation

```bash
pip install docflow[all]          # Everything
pip install docflow[pdf,llm]      # Lightweight: PyMuPDF + LLM only
pip install docflow[ocr,llm]      # Tesseract OCR + LLM
pip install docflow[docling,llm]  # Docling (best parsing) + LLM
```

Requires Python >= 3.11.

## Core API — 3 Ways to Use

### 1. One-liner (simplest)

```python
from docflow import extract

result = extract("invoice.pdf", schema=Invoice, model="openai/gpt-4o")
```

### 2. DocumentPipeline (configurable, reusable)

```python
from docflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="pymupdf",           # "pymupdf" | "tesseract" | "docling" | "smart"
    model="openai/gpt-4o",      # any litellm model string
    extraction_type="text",     # "text" | "vision" | "hybrid"
    extraction_mode="single",   # "single" | "multi"
    storage="local",            # None | "local" | Storage instance
)
result = pipeline.run_sync("invoice.pdf", schema=Invoice)
```

### 3. Manual Pipeline (full control)

```python
from docflow.workflow import Pipeline, Ingest, Parse, Extract, Validate, Review, Store

pipeline = Pipeline([
    Ingest(path="file.pdf"),
    Parse(parser="tesseract"),
    Extract(schema=Invoice, llm=my_llm, mode="multi", n_instances=3),
    Validate(validators=[RequiredFields(["total"])]),
    Review(rules=[OverallConfidenceBelow(0.7)]),
    Store(storage=LocalDocumentStore("./output")),
])
result = pipeline.run_sync()
```

## Defining Schemas

### Python class (recommended)

```python
from pydantic import BaseModel, Field

class Invoice(BaseModel):
    supplier_name: str = Field(description="Name of the supplier")
    invoice_number: str = Field(description="Invoice reference number")
    invoice_date: str = Field(description="Date of the invoice")
    total: float = Field(description="Total amount including tax")
    currency: str = Field(default="EUR", description="Currency code")
```

### YAML template

```python
from docflow.templates import load_template
Invoice = load_template("invoice")  # built-in: invoice, contract, receipt
```

## Parsers — Choosing the Right One

| Parser | Use when | Speed | Install |
|--------|----------|-------|---------|
| `"pymupdf"` | Digital/native PDFs | Fast (~100ms) | `docflow[pdf]` |
| `"tesseract"` | Scanned documents | Slow (1-5s/page) | `docflow[ocr]` |
| `"docling"` | Complex layouts, tables | Slow (4-5s/page) | `docflow[docling]` |
| `"smart"` | Mixed docs (auto-detects per page) | Varies | `docflow[pdf,ocr]` |
| `"azure-di"` | Cloud OCR, Azure Document Intelligence | API call | `docflow[azure]` |
| `"textract"` | Cloud OCR, AWS Textract | API call/page | `docflow[aws,pdf]` |
| `"google-docai"` | Cloud OCR, Google Document AI | API call | `docflow[gcp]` |

### Cloud OCR configuration

```python
# Azure Document Intelligence — or env vars AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT / _KEY
pipeline = DocumentPipeline(parser={"type": "azure-di", "model": "prebuilt-read"})

# AWS Textract — credentials via standard boto3 chain; pages rendered locally, no S3 needed
pipeline = DocumentPipeline(parser={"type": "textract", "region": "eu-west-1"})

# Google Document AI — or env vars GOOGLE_DOCAI_PROJECT / _LOCATION / _PROCESSOR_ID
pipeline = DocumentPipeline(parser={"type": "google-docai", "project": "p", "processor_id": "x"})
```

All parsers produce the same standardized `Document`: pages of **line-level blocks**, where OCR-based parsers also fill per-word `words` (text, bbox, confidence) and a line `confidence`. Native parsers (PyMuPDF) leave confidence empty — downstream code treats that as "no OCR ran". Docling is hybrid: when its internal OCR fires (scanned pages), the OCR cell confidences are attached to the layout blocks; native Docling parses report no OCR confidence, by design.

## Extraction Types

| Type | Pipeline | What happens |
|------|----------|-------------|
| `"text"` | Parse → Extract | Parser gives text, LLM reads text |
| `"vision"` | ExtractVision (no parser) | Pages rendered as images → vision LLM |
| `"hybrid"` | ExtractHybrid (no parser) | Vision + text agents parallel → vision decider |

**Vision and hybrid require `parser=None`:**

```python
pipeline = DocumentPipeline(parser=None, extraction_type="vision", model="openai/gpt-4o")
```

## Extraction Modes

| Mode | LLM calls | Description |
|------|-----------|-------------|
| `"single"` | 1 | One LLM call |
| `"multi"` | N+1 | N parallel calls at varied temperatures → decider picks best |

```python
pipeline = DocumentPipeline(extraction_mode="multi", n_instances=3)
```

## Output — ExtractionResult

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)

result.data                          # {"supplier_name": "Acme", "total": 1234.56}
result.fields["total"].value         # 1234.56
result.fields["total"].confidence    # 0.92
result.fields["total"].evidence[0].text        # "1234.56"
result.fields["total"].evidence[0].page_number # 0
result.fields["total"].evidence[0].bbox        # BoundingBox(x0=72, y0=130, x1=200, y1=148)
result.confidence                    # 0.85 (overall)
result.needs_review                  # True/False
result.review_reasons                # ["Field 'total' confidence below 0.8"]
result.review_verdicts               # [ReviewVerdict(reviewer="auditor", verdict="Approved")]
result.model_dump_json()             # full JSON serialization
```

## Validation

```python
from docflow.validation import RequiredFields, EvidenceRequired

pipeline = DocumentPipeline(
    validators=[
        RequiredFields(["supplier_name", "total"]),
        EvidenceRequired(["total"]),
    ],
)
```

## Review Rules

```python
from docflow.review import (
    OverallConfidenceBelow,
    FieldConfidenceBelow,
    AnyFieldConfidenceBelow,
    HasValidationErrors,
    FieldMissing,
    NoEvidence,
    LLMReviewer,
)

pipeline = DocumentPipeline(
    review_rules=[
        OverallConfidenceBelow(0.7),
        FieldConfidenceBelow({"total": 0.8}),
        FieldMissing(["total", "invoice_number"]),
    ],
)
```

### LLM Reviewer (prompt-driven)

```python
from docflow.review import LLMReviewer
from docflow.extraction.llm.litellm_adapter import LiteLLMAdapter

auditor = LLMReviewer(
    name="financial_auditor",
    prompt="Check if totals and line items are mathematically consistent.",
    llm=LiteLLMAdapter(model="openai/gpt-4o"),
)
pipeline = DocumentPipeline(review_rules=[auditor])
```

## Human Corrections

```python
result.correct_field("total", 1235.00, corrected_by="john", reason="OCR misread")
result.fields["total"].value           # 1235.00
result.fields["total"].original_value  # 1234.56 (preserved)
result.corrections                     # [FieldCorrection(...)]

result.approve(approved_by="john")     # or result.reject(rejected_by="john", reason="...")
result.review_status                   # "approved"
```

## Provenance

```python
prov = result.provenance("total")
p = prov["total"]
p.value, p.original_value, p.source_text, p.page, p.bbox
p.model_name, p.parser_name, p.confidence, p.evidence_confidence
p.validation_status, p.review_status, p.reviewed_by
p.corrected, p.corrected_by, p.correction_reason
```

## Privacy / Anonymization

```python
from docflow import DocumentPipeline, PrivacyPolicy
from docflow.privacy import PresidioProvider

pipeline = DocumentPipeline(
    parser="tesseract",
    privacy=PrivacyPolicy(
        provider=PresidioProvider(),
        mode="pseudonymize",    # "redact" | "mask" | "pseudonymize" | "hash"
        reversible=True,
        fail_closed=True,
    ),
)
```

## Domain Context

```python
pipeline = DocumentPipeline(
    context="You work in pharmaceutical regulatory affairs. Drug names should use INN format.",
)
```

## Batch Processing

```python
from docflow import DocumentPipeline, process_batch

pipeline = DocumentPipeline(parser="smart", model="openai/gpt-4o")
report = process_batch(
    files=["inv1.pdf", "inv2.pdf", "inv3.pdf"],
    schema=Invoice,
    pipeline=pipeline,
)
report.total, report.succeeded, report.failed, report.needs_review
report.average_confidence
report.top_review_reasons
report.to_csv()            # CSV string
report.to_dataframe()      # pandas DataFrame
```

## Document Comparison

```python
from docflow import compare_documents

comparison = compare_documents(
    files=["v1.pdf", "v2.pdf", "v3.pdf"],
    schema=Contract,
    pipeline=pipeline,
)
for field, cells in comparison.fields.items():
    diff = comparison.differences[field]
    print(f"{field}: {'SAME' if diff.all_agree else 'DIFFERENT'} — {diff.summary}")
```

## Search

```python
from docflow.search import search_document

result = search_document(document, "Acme Corp")
for hit in result.hits:
    print(f"Page {hit.page_number}, bbox: {hit.bbox}, context: {hit.context}")
```

## Screenshots

```python
from docflow.screenshots import screenshot_pages_sync

shots = screenshot_pages_sync("doc.pdf", output_dir="./pages", dpi=200)
```

## Quality Report

```python
from docflow import quality_report

report = quality_report(result)
report.score               # 0.85 — overall quality (0-1)
report.completeness_rate   # 7/8 fields have a non-None value
report.grounding_rate      # 7/7 present fields found in source text
report.evidence_coverage   # 7/7 present fields have evidence
report.mean_confidence     # average field confidence
report.auto_accept_rate    # fields passing auto-accept
report.correction_rate     # fields human-corrected
report.ok                  # True if score >= threshold
report.warnings            # human-readable issues
report.field_details       # per-field FieldQuality breakdown

# Works on batches too
batch_report = quality_report([result1, result2, result3])
batch_report.worst_fields  # fields with lowest avg quality

# Record quality over time (append-only JSONL)
from docflow.quality import QualityLog

log = QualityLog("./quality.jsonl")
await log.record(report, tags={"schema": "Invoice", "model": "gpt-4o"})
history = await log.history(last_n=50, tags={"schema": "Invoice"})
# Sync: log.record_sync(...), log.history_sync(...)
```

## Workflow Config (Portable YAML)

Define and run a full workflow from a YAML file — no Python imports needed:

```yaml
name: invoice-extraction
schema:
  supplier_name: {type: str, required: true, description: "Supplier"}
  total: {type: float, required: true, description: "Total amount"}
parser: smart
model: openai/gpt-4o
extraction_mode: multi
n_instances: 3
validation:
  - required_fields: [supplier_name, total]
review:
  - overall_confidence_below: 0.7
```

```python
from docflow import run_workflow

result = run_workflow("invoice.yaml", "invoice.pdf")
```

```bash
docflow run invoice.yaml invoice.pdf --output result.json
```

Export an existing pipeline:

```python
yaml_str = pipeline.export_yaml(Invoice, name="invoice")
```

## Storage

```python
pipeline = DocumentPipeline(storage="local")  # saves to .docflow_store/
# Saves: original.pdf, document.json, extraction.json, trace.json
# On failure: partial state auto-saved if storage is configured
```

## Error Handling

```python
from docflow.errors import WorkflowError

try:
    result = pipeline.run_sync("file.pdf", schema=Invoice)
except WorkflowError as e:
    print(e.result.errors)           # what went wrong
    print(e.result.state.document)   # partial state
    print(e.result.trace.events)     # trace up to failure
```

## Serve & Dockerize (HTTP Microservice)

Wrap any workflow config as an HTTP API — useful when extraction is one step in a larger multi-language pipeline.

```bash
pip install docflow[serve]  # adds fastapi, uvicorn, python-multipart
```

### Local server

```python
from docflow.serve import create_app, run_server
from docflow.workflow_config import load_workflow_config

config = load_workflow_config("workflow.yaml")
app = create_app(config)  # FastAPI app with /health, /schema, /extract
run_server("workflow.yaml", port=8000)
```

### Docker deployment

```python
from docflow.dockerize import generate_deployment

generate_deployment("workflow.yaml", "./deploy")              # stateless
generate_deployment("workflow.yaml", "./deploy", with_storage=True)  # with /data volume
```

### Endpoints

- `GET /health` — workflow name, version, model, parser
- `GET /schema` — field definitions
- `POST /extract` — upload file, returns structured data + quality_score + quality_ok

### CLI

```bash
docflow serve workflow.yaml --port 8000
docflow dockerize workflow.yaml --output ./deploy
docflow dockerize workflow.yaml --output ./deploy --with-storage
```

## CLI

```bash
docflow extract file.pdf --schema invoice --output result.json
docflow extract-folder ./invoices --schema invoice --output results.csv --parser smart
docflow run workflow.yaml invoice.pdf --output result.json
docflow serve workflow.yaml --port 8000
docflow dockerize workflow.yaml --output ./deploy --with-storage
docflow screenshot file.pdf -o ./pages --dpi 200
docflow templates list
docflow templates show invoice
docflow templates init invoice
```

## Key Imports

```python
# Top-level
from docflow import extract, DocumentPipeline, Pipeline, PrivacyPolicy
from docflow import process_batch, compare_documents

# Parsing
from docflow.parsing.pymupdf import PyMuPDFParser
from docflow.parsing.tesseract_parser import TesseractParser
from docflow.parsing.docling_parser import DoclingParser
from docflow.parsing.smart_parser import SmartParser

# Templates
from docflow.templates import load_template, list_templates

# Validation
from docflow.validation import RequiredFields, EvidenceRequired, TypeValidation

# Review
from docflow.review import (
    OverallConfidenceBelow, FieldConfidenceBelow, AnyFieldConfidenceBelow,
    HasValidationErrors, FieldMissing, NoEvidence, LLMReviewer,
)

# Privacy
from docflow.privacy import PrivacyPolicy, Anonymizer, PresidioProvider

# Storage
from docflow.storage.local import LocalDocumentStore

# LLM
from docflow.extraction.llm.litellm_adapter import LiteLLMAdapter

# Pipeline steps (for manual Pipeline)
from docflow.workflow import (
    Pipeline, Ingest, Parse, Extract, ExtractVision, ExtractHybrid,
    Anonymize, Validate, Review, Store,
)

# Utilities
from docflow.search import search_document
from docflow.screenshots import screenshot_pages_sync
from docflow.quality import quality_report, QualityReport, QualitySnapshot, QualityLog
from docflow.workflow_config import load_workflow_config, run_workflow, WorkflowConfig
from docflow.batch import process_batch, BatchReport
from docflow.comparison import compare_documents, ComparisonResult
```

## Schema Discovery

Auto-generate a schema from a document — the LLM reads it and suggests fields:

```python
from docflow import discover_schema

discovery = discover_schema("invoice.pdf")
print(discovery.document_type)     # "invoice"
print(discovery.fields)            # [DiscoveredField(name="supplier_name", type="str", ...)]

# Use immediately
Invoice = discovery.schema_class
result = extract("invoice.pdf", schema=Invoice)

# Or save as YAML template
with open("docflow_templates/my_invoice.yaml", "w") as f:
    f.write(discovery.yaml_template)
```

## Structured Tables (Docling parser only)

When using `parser="docling"`, tables are extracted as first-class objects:

```python
from docflow.documents.tables import Table, Cell

for page in document.pages:
    for table in page.tables:
        cell = table.cell_at(1, 1)
        cell.text              # "4,200"
        cell.row_headers       # ["Revenue"]
        cell.col_headers       # ["Q3 2024"]
        cell.bbox              # BoundingBox

        records = table.to_dict_records()  # [{"Q3 2024": "4,200", ...}]
```

Other parsers produce `page.tables = []`.

## Trust Scoring

DocFlow uses agreement + source verification, NOT LLM self-reported confidence:

```python
field.trust.agreement        # "4/5" (multi mode) or "" (single mode)
field.trust.agreement_ratio  # 0.8 (multi) or 0.0 (single — no consensus)
field.trust.found_in_source  # True/False
field.trust.auto_accept      # True = skip review, False = needs review
field.trust.score            # quantitative score (0-1)

# Scoring parameter: "qualitative" (binary) or "quantitative" (percentage)
pipeline = DocumentPipeline(scoring="quantitative")
```

Single agent: no consensus score, trust based on source verification only.
Multi agent: consensus percentage + source verification.

## Confidence Scores (OCR + LLM Consensus)

Confidence is split into two independent, optional axes. Neither ever breaks
the pipeline — when a score is not applicable it is `None`.

### OCR confidence (only when an OCR-based parser ran)

```python
result.ocr                       # OCRDocumentConfidence | None
result.ocr.score                 # 0-1, mean word confidence across the document
result.ocr.word_count
result.ocr.low_confidence_ratio  # fraction of words below 0.6

field = result.fields["total"]
field.ocr                        # OCRFieldConfidence | None
field.ocr.score                  # min word confidence of the matched span
field.ocr.match_method           # "exact_block" | "fuzzy_block" | "page_text" | "unmatched"
field.ocr.match_ratio            # 1.0 = exact, <1.0 = fuzzy match quality
field.ocr.matched_text           # the OCR text the value was matched to
```

Field-level scores are computed by matching the extracted value **back** to the
OCR words (evidence-hint text first, then the value itself; exact, then fuzzy
via SequenceMatcher). `None` document-level = no OCR in the pipeline.
`"unmatched"` field-level = OCR ran but the value couldn't be located (e.g.
reformatted dates, anonymized values).

### LLM consensus (only in multi-instance mode)

```python
field.consensus                  # FieldConsensus | None (None in single mode)
field.consensus.agreement        # "4/5" — candidates agreeing with the FINAL value
field.consensus.agreement_ratio  # 0.8
field.consensus.majority_ratio   # largest candidate cluster; if > agreement_ratio,
                                 # the decider overrode the majority
field.consensus.n_instances      # instances launched
field.consensus.n_succeeded      # instances that returned valid JSON
```

## Eval Harness

Measure extraction accuracy against ground truth (corrections = your gold set):

```python
from docflow.eval import EvalHarness

harness = EvalHarness()
harness.add_ground_truth(approved_result)  # correct values
report = harness.compare_results(predicted=new_results)

report.overall_accuracy     # 0.85
report.hallucination_rate   # 0.03
report.field_accuracy       # {"supplier_name": 0.95, "total": 0.88}
report.field_scores["total"]  # FieldScore(exact_match=8, fuzzy_match=1, wrong=1, ...)
```

## Approval Workflow

```python
result.correct_field("total", 1235.00, corrected_by="john", reason="OCR error")
result.approve(approved_by="john")
# result.review_status = "approved", result.reviewed_by = "john", result.reviewed_at = datetime

result.reject(rejected_by="john", reason="wrong document")
# result.review_status = "rejected", result.rejection_reason = "wrong document"
```

## Field Provenance

Full audit chain per field:

```python
prov = result.provenance("total")
p = prov["total"]
p.value, p.original_value, p.corrected, p.corrected_by, p.correction_reason
p.source_text, p.page, p.bbox, p.block_id, p.evidence_confidence
p.model_name, p.parser_name, p.validation_status
p.review_status, p.reviewed_by, p.review_verdicts
```

## Storage Queries

```python
store = LocalDocumentStore("./output")
await store.list_documents()          # all document IDs
await store.get_pending_reviews()     # needs_review=True, status=pending
await store.get_by_status("approved") # reviewed and approved
await store.get_by_status("rejected") # reviewed and rejected
```

## MCP Server (AI Agent Integration)

DocFlow runs as an MCP server with 14 tools any AI agent can call:

```bash
pip install docflow[mcp]
docflow-mcp  # starts the server
```

Tools: `extract_document`, `extract_with_vision`, `discover_schema`, `compare_documents`, `process_batch`, `list_templates`, `show_template`, `search_in_document`, `get_pending_reviews`, `get_extraction_result`, `correct_field`, `approve_document`, `reject_document`, `screenshot_document`.

## Project Structure

```
src/docflow/
  __init__.py          # Public API (extract, DocumentPipeline, Pipeline)
  api.py               # extract() one-liner
  processor.py         # DocumentPipeline
  batch.py             # process_batch, BatchReport
  comparison.py        # compare_documents
  discover.py          # discover_schema (auto-generate schemas)
  search.py            # search_document
  screenshots.py       # screenshot_pages
  quality.py           # quality_report (per-result quality assessment)
  workflow_config.py   # Portable YAML workflow config, run_workflow, export
  serve.py             # FastAPI server (create_app, run_server)
  dockerize.py         # Docker deployment generator
  eval.py              # EvalHarness (accuracy measurement)
  mcp_server.py        # MCP server (14 tools for AI agents)
  constants.py         # DEFAULT_DPI
  errors.py            # All exception classes
  documents/           # Document, Page, Block, Evidence, Table, Cell
  extraction/          # ExtractionEngine, VisionExtractionEngine, HybridExtractionEngine
    llm/               # LLMAdapter protocol, LiteLLMAdapter
  parsing/             # Parser protocol, PyMuPDF, Tesseract, Docling, Smart
  ocr/                 # OCREngine protocol, TesseractOCR, preprocessing
  rendering/           # PDF page to image rendering
  templates/           # YAML template registry and loader
  validation/          # Validator protocol, built-in validators
  review/              # ReviewRule protocol, LLMReviewer
  privacy/             # PrivacyPolicy, Anonymizer, Presidio, image redaction
  storage/             # Storage protocol, LocalDocumentStore (with query methods)
  strategies/          # Strategy protocol
  workflow/            # Pipeline, PipelineState, all step classes
  observability/       # Trace, TraceEvent
  cli/                 # Click CLI
```

## Dev Commands

```bash
uv pip install -e ".[all,dev]"         # Install everything
uv run pytest -m "not integration"     # Fast tests (432 tests)
uv run pytest                          # All tests including integration
uv run ruff check src/ tests/          # Lint
uv run ruff format src/ tests/         # Format
```
