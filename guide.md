<p align="center">
  <img src="docs/assets/docuflow-logo.png" alt="DocuFlow logo" width="920">
</p>

# Complete User Guide

> This guide is the practical user guide. The deeper technical library documentation,
> including public APIs, parameters, selectable options, data models, deployment,
> extension points, and error handling, lives under [`docs/`](docs/).

> DocuFlow turns unstructured documents into production-ready data. Unlike typical extraction tools that stop at raw JSON, DocuFlow adds evidence, consensus, verification, validation, and auditability so you can trust, review, and ship the result.

> Licensing note: DocuFlow's dependencies are permissive and commercially usable.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation](#2-installation)
3. [Quick Start](#3-quick-start)
4. [Core Concepts](#4-core-concepts)
5. [Defining Schemas](#5-defining-schemas)
5b. [The Levels of "auto"](#5b-the-levels-of-auto)
6. [Parsers](#6-parsers)
6b. [Structured Tables](#6b-structured-tables)
7. [Extraction Engines](#7-extraction-engines)
8. [The Pipeline](#8-the-pipeline)
9. [Validation](#9-validation)
10. [Review](#10-review)
11. [Human Corrections & Approval](#11-human-corrections--approval)
12. [Provenance](#12-provenance)
13. [Privacy & Anonymization](#13-privacy--anonymization)
14. [Batch Processing](#14-batch-processing)
14b. [Routing Mixed Document Streams](#14b-routing-mixed-document-streams)
15. [Document Comparison](#15-document-comparison)
16. [Document Search & Highlighting](#16-document-search--highlighting)
17. [Screenshots](#17-screenshots)
18. [Quality Report](#18-quality-report)
18b. [Workflow Config](#18b-workflow-config)
18c. [Serve & Dockerize (Deployment)](#18c-serve--dockerize-deployment)
18d. [PDF Form Filling](#18d-pdf-form-filling)
19. [Storage](#19-storage)
20. [Observability & Traces](#20-observability--traces)
21. [Error Handling](#21-error-handling)
22. [CLI Reference](#22-cli-reference)
23. [API Reference](#23-api-reference)

---

## 1. Introduction

### What DocuFlow Does

DocuFlow is a Python library that extracts structured data from business documents — invoices, contracts, receipts, claims, KYC forms — using LLMs. You define what fields you want (as a Pydantic model), point it at a PDF, and get back:

- **Extracted values** matching your schema
- **Evidence** linking each value to its source text, page number, and bounding box
- **Two confidence scores** — OCR confidence (did we read the page correctly?) and LLM consensus (did independent runs interpret it the same way?) 
- **Validation results** against your business rules
- **Review verdicts** from configurable rules and LLM-powered reviewers
- **Full audit trail** of corrections, approvals, and processing history

### What Makes DocuFlow Different

Most extraction tools stop at "here's your JSON." DocuFlow covers what happens after extraction:

- **Evidence grounding**: every field traces to a specific location in the source document
- **Multi-agent consensus**: run multiple LLMs in parallel and let a decider pick the best answer
- **Human-in-the-loop**: review rules, LLM reviewers, corrections, approve/reject workflow
- **Privacy-first**: anonymize PII before it reaches the LLM
- **Production tooling**: batch processing, document comparison, CSV export, token/cost accounting
- **Self-containerizing**: any workflow exports to YAML and deploys itself as a Docker microservice

### What It Can Process

DocuFlow accepts these source types today:

- PDF: `.pdf`
- Images: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.gif`, `.webp`
- Text-like files: `.txt`, `.md`, `.html`, `.htm`, `.csv`, `.json`, `.xml`
- Office documents: `.docx`
- Spreadsheets: `.xlsx`
- Email: `.eml`

With `parser="auto"`, DocuFlow routes each source to the right path and still normalizes
everything to the same internal `Document` model.

### Three Ways to Use DocuFlow

Pick the level of ceremony that fits the job — they all run the same pipeline underneath:

**1. The one-liner** — for scripts, notebooks, and trying things out:

```python
from docuflow import extract

result = extract("invoice.pdf", schema=Invoice, model="openai/gpt-4o")
```

**2. As a library** — `DocumentPipeline` for reusable configuration, or the manual
`Pipeline` with explicit steps for full control. This is the way when extraction is
part of a larger Python application:

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(parser="smart", extraction_mode="multi", n_instances=3)
result = pipeline.run_sync("claim_form.pdf", schema=InsuranceClaim)
```

**3. As configuration — no code at all.** The entire workflow (schema, parser, model,
validation, review rules) lives in one YAML file. Run it from the CLI, serve it as an
HTTP API, or generate a Docker deployment from it — the YAML file *is* the deployable
artifact, which means workflows can be versioned, reviewed, and shared without touching
Python:

```bash
docuflow run claims.yaml claim_form.pdf --output result.json
docuflow serve claims.yaml --port 8000
docuflow dockerize claims.yaml --output ./deploy
```

See [Workflow Config](#18b-workflow-config) and [Serve & Dockerize](#18c-serve--dockerize-deployment).

### Architecture Overview — How the Backend Works

DocuFlow processes documents through a configurable pipeline of steps:

```
Ingest → Parse → [Anonymize] → Extract → [Validate] → [Review] → [Store]
```

Steps in brackets are optional. Here's what happens at each stage, in detail:

#### Step 1: Ingest

The pipeline reads the file from disk and creates a `Document` object with metadata — file name, path, size, SHA-256 hash, MIME type. No content is read yet; this is just registration.

The Document gets a UUID that follows it through every subsequent step. This ID is what links extraction results, evidence, traces, and corrections back to the source file.

#### Step 2: Parse

The parser converts the raw PDF into structured content. This is where the heavy lifting happens.

**What the parser produces:**
- `document.pages` — a list of `Page` objects, one per page
- Each `Page` has `blocks` — individual text elements with bounding boxes (x0, y0, x1, y1 coordinates on the page)
- Each `Block` has `text`, `block_type` (paragraph, title, table, image, etc.), and optionally `confidence` (from OCR)
- `document.raw_text` — all page text concatenated, which is what gets sent to the LLM

**The parsers produce different levels of richness:**
- **pdfplumber**: reads the PDF's embedded text layer directly. Fast, line-level blocks with per-word bboxes — but no confidence scores (the text is either there or it isn't). Fails on scanned PDFs (returns empty text).
- **Tesseract**: renders each page to an image at 200 DPI, runs OCR, produces line-level blocks with per-word bboxes AND confidence scores (0-1). Works on scanned documents.
- **Docling**: uses IBM's document AI model. Understands layout (titles, paragraphs, headers, footers, formulas). Produces structured `Table` objects with cell-level data, row/column headers, and spans. When its internal OCR fires on scanned pages, word confidences are attached too.
- **Smart**: runs pdfplumber first. For each page, checks if the text is usable (enough characters, not garbled, not just images). Pages that fail get OCR'd with Tesseract. This means digital pages are fast and scanned pages still work.
- **Cloud OCR (azure-di, textract, google-docai)**: managed OCR services producing the same line/word structure with confidences — higher accuracy at a per-page API cost.

After parsing, `document.status` changes from `"ingested"` to `"parsed"`.

#### Step 3: Anonymize (optional)

If a `PrivacyPolicy` is configured, the Anonymize step runs before the document text reaches the LLM.

**What happens internally:**
1. The privacy provider (Presidio by default) scans the document text for PII entities — names, emails, phone numbers, IBANs, etc.
2. Detected entities are replaced according to the chosen mode:
   - `redact`: replaced with `[REDACTED]`
   - `mask`: replaced with `M**** R****`
   - `pseudonymize`: replaced with stable tokens like `PERSON_001`, `EMAIL_001` (same entity = same token within the document)
   - `hash`: replaced with SHA-256 hash
3. If `reversible=True`, the token-to-original mappings are saved so extractions can be restored later
4. `document.raw_text` and each `page.text` are replaced with the anonymized versions
5. The original text is preserved in `state.metadata["original_raw_text"]`

If `fail_closed=True` (default) and anonymization fails, the pipeline stops — no raw PII reaches the LLM.

#### Step 4: Extract

This is where the LLM reads the document and produces structured data. The extraction engine:

1. **Builds a prompt** containing:
   - A system message with extraction rules ("extract only values present in the text, don't hallucinate, return JSON")
   - The user's schema as both human-readable field descriptions and a JSON schema
   - A concrete example of the expected output format using the actual field names
   - The document text organized by page (or page images for vision mode)
   - Optional domain context ("you are an insurance claims processor")

2. **Calls the LLM** with JSON mode enforced (`response_format={"type": "json_object"}`). The LLM returns a JSON object with two keys:
   - `"data"`: the extracted field values matching the schema
   - `"evidence"`: per-field evidence with page number, source text quote, and confidence

3. **Parses the response**. If JSON parsing fails, strips markdown fences and retries. If retry fails, raises `SchemaExtractionError`.

4. **Validates against the schema** using Pydantic `model_validate()`. If the LLM's output doesn't match the schema, raises `SchemaExtractionError`.

5. **Grounds the evidence**. For each field, `attach_evidence()` searches ALL pages for the LLM's quoted text (not trusting the LLM's reported page number). If the text matches a block, the evidence gets that block's bounding box and confidence. If found in page text but not a specific block, it gets the page number without a bbox.

6. **Computes trust gates**:
   - In **single mode**: trust is based on whether the value was found in the source text
   - In **multi mode**: N parallel LLM calls run at different temperatures. A decider LLM reviews all candidates and picks the best value per field. Trust is based on how many agents agreed (consensus) plus source verification
   - `trust_gate = True` only when all agents agree AND the value exists in the source text

7. **Returns an `ExtractionResult`** with the extracted data, per-field details (value, trust, evidence, validation status), and overall confidence.

#### How Multi-Agent Extraction Works Internally

When `extraction_mode="multi"` with `n_instances=5`:

1. The same prompt is sent to the LLM 5 times in parallel, each at a slightly different temperature (auto-generated spread around 0.3 for diversity)
2. Each call returns independently — failures are filtered out
3. If all 5 fail, the pipeline raises an error
4. If only 1 succeeds, its result is used directly (no decider needed)
5. If 2+ succeed, a **decider prompt** is built:
   - Contains all candidate extractions as numbered JSON blocks
   - Asks the decider to compare field by field and pick the most consistent value per field
   - The decider also uses JSON mode
6. The decider's output is parsed, validated, and evidence-grounded like a normal extraction

For **hybrid mode**, it's the same but with two types of agents running in parallel:
- N vision agents (page images → vision LLM)
- N text agents (OCR markdown → text LLM)
- The decider is a **vision** model that sees both the candidates AND the actual page images, so it can verify values visually

#### Step 5: Validate (optional)

Validators check the extraction result against rules:
- `RequiredFields(["total", "supplier_name"])` — are these fields present and non-None?
- `EvidenceRequired(["total"])` — does the field have source evidence?
- `TypeValidation()` — are values the right type?
- Custom rules via `CustomRule(name, fn)`

Each field's `validation_status` is updated to `"valid"`, `"warning"`, or `"error"`. Validation errors are collected on `result.validation_errors`.

#### Step 6: Review (optional)

The Review step checks if the document needs human attention. It runs two types of checks:

**Rule-based checks** (fast, no LLM call):
- Confidence thresholds (overall or per-field)
- Missing critical fields
- Validation errors present
- Fields without evidence

**LLM reviewer checks** (one LLM call each):
- Custom prompt-driven reviewers that inspect the extracted data, evidence, and document text
- Each reviewer returns a structured `ReviewVerdict` with "Approved" or "Not Approved" plus reasoning

If any check triggers, `result.needs_review = True` and the reasons are recorded in `result.review_reasons`. All LLM reviewer verdicts (even approvals) are stored in `result.review_verdicts`.

#### Step 7: Store (optional)

If storage is configured (`storage="local"`), the Store step persists everything to disk:
- `{document_id}/original.pdf` — copy of the source file
- `{document_id}/document.json` — the parsed Document (pages, blocks, text, tables)
- `{document_id}/extraction.json` — the ExtractionResult (data, fields, evidence, trust, review status, corrections)
- `{document_id}/filling.json` — the FillingResult for PDF form filling workflows
- `{document_id}/trace.json` — processing trace (every step's timing, model calls, errors)

**On failure**: if the pipeline fails at any step and storage is configured, partial state is automatically saved. The trace shows exactly which step failed and why.

#### The PipelineState Object

All steps communicate through a single `PipelineState` object that carries:
- `document` — the Document (populated by Ingest, enriched by Parse)
- `extraction_result` — the ExtractionResult (populated by Extract)
- `trace` — accumulates events from every step (timing, model calls, errors)
- `status` — "pending", "running", "completed", or "failed"
- `errors` — list of error messages
- `metadata` — free-form dict for passing data between steps (anonymization result, original text, etc.)

Each step receives the state, does its work, and returns the updated state. The Pipeline runs steps sequentially and stops on the first failure.

---

## 2. Installation

### Full Installation

```bash
pip install docuflow[all]
```

This installs everything: all parsers (pdfplumber, Tesseract, Docling, and the Azure/AWS/Google cloud OCR SDKs), LLM support, serving, privacy/anonymization, and all dependencies. This is the heaviest option (~500MB+ due to PyTorch from Docling).

### Selective Installation

Install only what you need:

```bash
pip install docuflow[pdf,llm]        # pdfplumber parser + LLM (lightweight)
pip install docuflow[ocr,llm]        # Tesseract OCR + LLM
pip install docuflow[docling,llm]    # Docling parser + LLM (best quality)
pip install docuflow[forms]          # PDF form filling
pip install docuflow[privacy]        # Presidio anonymization
```

### Optional Dependency Groups

| Group | Packages | Purpose |
|-------|----------|---------|
| `pdf` | pdfplumber, pypdfium2 | PDF text extraction (pdfplumber) and page rendering (pypdfium2) |
| `forms` | pypdf, reportlab, pdfplumber | PDF form filling, explicit static-PDF overlays, and opt-in blank detection |
| `ocr` | pytesseract, Pillow | OCR with Tesseract |
| `llm` | litellm | LLM calls (OpenAI, Anthropic, Gemini, etc.) |
| `privacy` | presidio-analyzer, presidio-anonymizer | PII detection and anonymization |
| `docling` | docling | Advanced document parsing with layout understanding |
| `azure` | azure-ai-documentintelligence | Azure Document Intelligence cloud OCR |
| `aws` | boto3 | AWS Textract cloud OCR |
| `gcp` | google-cloud-documentai | Google Document AI cloud OCR |
| `serve` | fastapi, uvicorn, python-multipart | HTTP serving and dockerize |
| `mcp` | mcp | MCP server for AI agents |
| `jupyter` | nest_asyncio | Sync API in Jupyter notebooks (see below) |
| `all` | All of the above | Everything |
| `dev` | pytest, pytest-asyncio, pytest-cov, ruff | Development tools |

### Installation Size

DocuFlow itself is ~3 MB. The dependencies vary significantly by what you install:

| Installation | Disk space | What you get |
|-------------|-----------|-------------|
| `docuflow` (core only) | ~15 MB | Pydantic, YAML, aiofiles, click — no parsing or LLM |
| `docuflow[pdf]` | ~70 MB | + pdfplumber (~50 MB) — digital PDF parsing |
| `docuflow[ocr]` | ~30 MB | + pytesseract + Pillow (~15 MB) — OCR (requires Tesseract binary) |
| `docuflow[llm]` | ~80 MB | + litellm (~55 MB) + OpenAI/HTTP clients |
| `docuflow[forms]` | ~20 MB | + pypdf + reportlab — write values into PDF forms |
| `docuflow[pdf,llm]` | ~140 MB | pdfplumber + LLM — the lightweight production setup |
| `docuflow[ocr,llm]` | ~110 MB | Tesseract + LLM — for scanned documents |
| `docuflow[privacy]` | ~50 MB | + Presidio analyzer + anonymizer + spaCy model |
| `docuflow[docling]` | ~800 MB | + Docling + PyTorch (~470 MB) + transformers — best parsing quality |
| `docuflow[mcp]` | ~30 MB | + MCP SDK + uvicorn — AI agent integration |
| `docuflow[all]` | ~1.3 GB | Everything including Docling/PyTorch |

**Recommendation:** Start with `docuflow[pdf,llm]` (~140 MB) for digital PDFs. Add `[ocr]` if you have scanned documents. Only add `[docling]` if you need advanced table extraction — it pulls in PyTorch which is the bulk of the size.

### Requirements

- Python >= 3.11
- For Tesseract parser: Tesseract binary must be installed on the system
- For LLM extraction: API key for your chosen provider (set via environment variable)

---

## 3. Quick Start

### Simplest Usage — One Function Call

```python
from pydantic import BaseModel
from docuflow import extract

class Invoice(BaseModel):
    supplier_name: str
    invoice_number: str
    total: float

# Set your API key
import os
os.environ["OPENAI_API_KEY"] = "sk-..."

result = extract("invoice.pdf", schema=Invoice)
print(result.data)
# {"supplier_name": "Acme Corp", "invoice_number": "INV-001", "total": 1234.56}
```

### Using a Built-in Template

```python
from docuflow import extract
from docuflow.templates import load_template

Invoice = load_template("invoice")
result = extract("invoice.pdf", schema=Invoice)
```

### Reusable Pipeline

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="tesseract",
    model="openai/gpt-4o",
    normalize_output=False,  # default: preserve exact source text
    storage="local",
)

# Process multiple documents with the same config
for pdf in ["inv1.pdf", "inv2.pdf", "inv3.pdf"]:
    result = pipeline.run_sync(pdf, schema=Invoice)
    print(f"{pdf}: {result.data['total']}")
```

Set `normalize_output=True` if you want DocuFlow to canonicalize textual values such as ISO dates instead of preserving the exact source wording.

### Inspecting Results

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)

# The extracted data as a dict
print(result.data)

# Per-field details
for name, field in result.fields.items():
    print(f"\n{name}:")
    print(f"  Value: {field.value}")
    print(f"  Trust gate: {field.trust_gate}")
    if field.trust:
        print(f"  Trust: {field.trust.agreement} agreed, found_in_source={field.trust.found_in_source}")
        print(f"  Gate: {field.trust.trust_gate}")
    print(f"  Validation: {field.validation_status}")
    for ev in field.evidence:
        print(f"  Evidence: page {ev.page_number}, text={ev.text!r}")
        if ev.bbox:
            print(f"    BBox: ({ev.bbox.x0}, {ev.bbox.y0}) -> ({ev.bbox.x1}, {ev.bbox.y1})")

# Overall result
print(f"\nOverall confidence: {result.confidence:.2f}")
print(f"Needs review: {result.needs_review}")
print(f"Model used: {result.model_name}")

# OCR confidence (None unless an OCR-based parser ran)
if result.ocr:
    print(f"OCR: {result.ocr.score:.2f} over {result.ocr.word_count} words")

# Token usage and cost
if result.usage:
    print(f"Tokens: {result.usage.total_tokens} across {result.usage.n_llm_calls} LLM calls")
    if result.usage.cost_usd is not None:
        print(f"Cost: ${result.usage.cost_usd:.4f}")
```

### Using DocuFlow in Jupyter Notebooks

DocuFlow's sync API (`extract()`, `run_workflow()`, `pipeline.run_sync()`,
`router.route_sync()`) uses `asyncio.run()` internally. Jupyter already runs its own
event loop, which normally causes a `RuntimeError: Cannot call run_sync() from within
a running event loop` error.

DocuFlow handles this automatically when `nest_asyncio` is installed:

```bash
pip install nest_asyncio
# or
pip install "docuflow[jupyter]"
```

Once installed, the sync API works in notebooks with no code changes. If
`nest_asyncio` is not installed, DocuFlow raises a clear error pointing to the
install command.

Alternatively, use the async API directly — Jupyter supports `await` at the cell
top level without any extra packages:

```python
# async API — works in Jupyter without nest_asyncio
result = await extract_async("invoice.pdf", schema=Invoice)
report = await router.route(["a.pdf", "b.pdf"])
result = await pipeline.run("invoice.pdf", schema=Invoice)
```

---

## 4. Core Concepts

### Document

A `Document` represents a file and all derived content. After ingestion, it has metadata (file name, path, size, hash, MIME type). After parsing, it gets populated with pages, blocks, and text.

```python
from docuflow.documents.models import Document

doc = Document.from_file_sync("invoice.pdf")
print(doc.id)                    # UUID
print(doc.metadata.file_name)    # "invoice.pdf"
print(doc.metadata.mime_type)    # "application/pdf"
print(doc.status)                # "ingested"
```

### Page

A `Page` represents one page of the document, with its text content and layout blocks.

```python
for page in document.pages:
    print(f"Page {page.page_number}: {page.block_count} blocks")
    print(f"  Dimensions: {page.width} x {page.height}")
    print(f"  Text: {page.text[:100]}...")
```

### Block

A `Block` is a line-level text element on a page with its position (bounding box) and,
for OCR-based parsers, per-word detail: each `Word` in `block.words` carries its own
text, bbox and recognition confidence. Native parsers (pdfplumber) fill `words` with
bboxes but no confidence — there is no OCR step to be uncertain about.

```python
for block in page.blocks:
    print(f"  [{block.block_type.value}] {block.text[:50]}")
    if block.bbox:
        print(f"    Position: ({block.bbox.x0}, {block.bbox.y0}) -> ({block.bbox.x1}, {block.bbox.y1})")
    if block.confidence is not None:
        print(f"    OCR confidence: {block.confidence:.2f}")
```

Block types: `TEXT`, `TITLE`, `TABLE`, `IMAGE`, `HEADER`, `FOOTER`, `LIST_ITEM`, `FORMULA`, `PARAGRAPH`.

### Evidence

An `Evidence` object links an extracted field value back to a specific location in the source document.

```python
evidence = result.fields["total"].evidence[0]
print(evidence.document_id)   # which document
print(evidence.page_number)   # which page (0-indexed)
print(evidence.text)          # the source text snippet
print(evidence.bbox)          # position on page (BoundingBox)
print(evidence.block_id)      # which block it matched to
print(evidence.confidence)    # OCR confidence (if available)
```

Evidence is grounded by locating the text in the document — it doesn't trust the LLM's
reported page number. The bbox covers exactly the matched words (not the whole line), and
`evidence.rects` carries one rectangle per (page, line) segment for quotes that span
lines or pages. If the text is found only in page text, the evidence gets the page number
but no bbox.

### ExtractionResult

The complete output of the extraction pipeline. Contains the extracted data, per-field details, review status, corrections, and provenance.

Key fields:
- `data` — extracted values as a dict
- `fields` — dict of `ExtractedField` objects with trust gate, evidence, validation status
- `confidence` — overall acceptance ratio (average of field trust gates)
- `ocr` — document-level OCR confidence (`None` when no OCR ran)
- `usage` — aggregated LLM token usage and cost (`None` when not reported)
- `needs_review` — True if any review rule flagged this document
- `review_status` — "pending", "approved", or "rejected"
- `review_reasons` — why it was flagged
- `review_verdicts` — structured verdicts from LLM reviewers
- `corrections` — audit trail of human corrections
- `validation_errors` — validation rule failures

---

## 5. Defining Schemas

### Python Classes (Recommended)

Define your extraction schema as a Pydantic `BaseModel`. Use `Field(description=...)` to help the LLM understand what to extract.

```python
from pydantic import BaseModel, Field

class Invoice(BaseModel):
    supplier_name: str = Field(description="Name of the supplier or vendor")
    invoice_number: str = Field(description="Invoice reference number")
    invoice_date: str = Field(description="Date the invoice was issued")
    currency: str = Field(default="EUR", description="Currency code (ISO 4217)")
    subtotal: float | None = Field(default=None, description="Amount before tax")
    vat_amount: float | None = Field(default=None, description="VAT/tax amount")
    total: float = Field(description="Total amount including tax")
```

Tips:
- Use `str` for dates (the LLM will format them as it reads them)
- Use `float | None` for optional numeric fields
- The `description` is sent to the LLM in the prompt — be specific
- The field name itself matters — `supplier_name` is clearer than `name`

### Nested Models

```python
class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float

class Invoice(BaseModel):
    supplier_name: str
    total: float
    line_items: list[LineItem] = Field(default_factory=list)
```

### YAML Templates

DocuFlow ships with 3 built-in templates and supports user-defined YAML templates.

```python
from docuflow.templates import load_template, list_templates

# See what's available
for t in list_templates():
    print(f"{t.name} ({t.source}): {t.description}")

# Load a template — returns a Pydantic class
Invoice = load_template("invoice")
Contract = load_template("contract")
Receipt = load_template("receipt")
```

Built-in templates:
- **invoice** — supplier, number, dates, totals, VAT, line items
- **contract** — type, parties, dates, terms, liability, governing law
- **receipt** — merchant, date, total, payment method, items

### Custom YAML Templates

Create a YAML file in `./docuflow_templates/` or `~/.docuflow/templates/`:

```yaml
# ./docuflow_templates/purchase_order.yaml
name: purchase_order
version: "1.0"
description: "Purchase order extraction schema"
fields:
  po_number:
    type: str
    required: true
    description: "Purchase order number"
  buyer:
    type: str
    required: true
  seller:
    type: str
    required: true
  order_date:
    type: date
    required: true
  total:
    type: float
    required: true
  items:
    type: list
    required: false
    item_fields:
      description:
        type: str
        required: true
      quantity:
        type: float
      unit_price:
        type: float
      amount:
        type: float
        required: true
```

Supported types: `str`, `int`, `float`, `bool`, `date`, `datetime`, `list` (with `item_fields` or `item_type`).

Template discovery order: `./docuflow_templates/` > `~/.docuflow/templates/` > built-in. First match wins, so placing a file with the same name as a built-in template overrides it.

### Initializing Templates

Copy a built-in template to your project for customization:

```bash
docuflow templates init invoice
# Creates ./docuflow_templates/invoice.yaml
```

### Auto-Discovering Schemas

Don't know what fields are in your document? Let the LLM figure it out:

```python
from docuflow import discover_schema

# LLM reads the document and suggests a schema
discovery = discover_schema("invoice.pdf")

print(discovery.document_type)  # "invoice"
print(discovery.description)    # "A supplier invoice with line items"

# See what fields were found
for f in discovery.fields:
    print(f"  {f.name}: {f.type} ({'required' if f.required else 'optional'})")
    print(f"    {f.description}")
```

The result gives you three things:

**1. A ready-to-use Pydantic class:**
```python
Invoice = discovery.schema_class

# Use it immediately for extraction
from docuflow import extract
result = extract("invoice.pdf", schema=Invoice)
```

**2. A YAML template you can save and customize:**
```python
print(discovery.yaml_template)
# name: invoice
# version: "1.0"
# fields:
#   supplier_name:
#     type: str
#     required: true
#     description: "Vendor name"
#   total:
#     type: float
#     required: true
#     description: "Total amount"

# Save for reuse
with open("docuflow_templates/my_invoice.yaml", "w") as f:
    f.write(discovery.yaml_template)
```

**3. The raw field list for inspection:**
```python
for f in discovery.fields:
    print(f.name, f.type, f.required, f.description)
```

Parameters:
- `path` — path to the document
- `model` — LLM model (default: `"openai/gpt-4o"`)
- `parser` — which parser to use for reading the document (default: `"auto"`, source-aware)

This is useful when you have a new document type and want a quick starting point. Discover the schema from one example, review/edit the YAML, then use it for batch processing.

---

## 5b. The Levels of "auto"

DocuFlow has three different "auto" mechanisms, and they are easy to confuse because they all promise the same thing — "I'll figure it out for you." But they act at **different stages of the pipeline**, decide **different questions**, and read **different signals**. Knowing the split is the difference between "it just works" and "why did it miss the scanned page?"

| Level | Knob | Question it answers | Decision unit | Signal it reads | When it runs |
|---|---|---|---|---|---|
| **1. Parser selection** | `parser="auto"` *(default)* | *Which parser* reads the file? | Whole document | File type (`source_kind`) | Before parsing |
| **2. Per-page reading** | `parser="smart"` | *How is each page read* — native text or OCR? | A single page | Does the page have a usable text layer? | During parsing |
| **3. Extraction escalation** | `extraction_type="auto"` | *Which modality extracts* — text or vision? | Whole document | Measured OCR confidence, after parsing | After parsing, before the LLM |

They are **independent** and **stack**: Level 1 chooses a parser, Level 2 can be that parser's internal per-page strategy, and Level 3 sits above both and may throw the parsed text away in favour of vision. You can use any one without the others.

### Level 1 — `parser="auto"`: pick a parser by *file type*

The default. It looks at the document's `source_kind` **once** and routes the whole file to one parser. It does **not** look at content quality.

| Source | Parser chosen |
|---|---|
| PDF | `pdfplumber` (native text layer) — but see the nuance below |
| Image (`png`, `jpg`, `tiff`, …) | `tesseract` (OCR) |
| Office / spreadsheet (`docx`, `xlsx`) | `docling` |
| Text-like (`txt`, `md`, `html`, `csv`, `json`, `xml`, `eml`) | none — ingestion already produced usable text |

Because it routes purely by type, for PDFs it assumes a real text layer exists. A **scanned PDF** (images, no text layer) parses to near-empty text and `parser="auto"` alone will not catch that — Levels 2 and 3 exist precisely for that case.

> **Nuance:** when you combine `parser="auto"` with `extraction_type="auto"`, the auto-parser *upgrades* its PDF choice from `pdfplumber` to the **smart** parser automatically (the `auto_mode` path). So `parser="auto", extraction_type="auto"` already gives you per-page reading for PDFs without naming `smart` yourself.

### Level 2 — `parser="smart"`: pick native-vs-OCR *per page*

`SmartParser` works **inside** a single PDF. It goes page by page: a page with a usable native text layer is read directly (fast, free); a page that fails that test falls back to Tesseract OCR. One file can therefore come back as a *mix* of native and OCR'd pages.

A page triggers OCR when its text is shorter than `min_text_length` (default 20 chars), it has no text blocks, it has embedded images but little text, or more than ~10% of its characters are garbled. This is what makes **part-digital, part-scanned** PDFs work — the exact case `parser="auto"` misses.

### Level 3 — `extraction_type="auto"`: escalate text → vision on *poor quality*

This is **not a parser**. It runs after parsing and decides whether the *text that came out* is trustworthy enough to extract from, or whether the document should be re-read by a **vision LLM** instead. The signal is measured, not guessed: it reads the OCR confidence produced during parsing.

It escalates to vision (or hybrid) when:
- there is almost no text at all — below `min_chars_per_page` (default 20) per page — *this is what catches scanned PDFs*, or
- mean OCR confidence is below `min_ocr_score` (default 0.6), or
- more than `max_low_confidence_ratio` of words are low-confidence (default 40%).

Otherwise it stays on the cheap text path. The choice and its reason are recorded on the result (`result.escalated`, `result.escalation_reason`). See [Auto Extraction](#auto-extraction-extraction_typeauto) for the full details, thresholds, and the privacy interaction.

### How they compose

The "I don't know what these documents look like" combo:

```python
DocumentPipeline(parser="smart", extraction_type="auto")
```

Walking the levels for one PDF:

```
Level 1  parser picks how to read the file        → smart (per-page)
Level 2  each page: native text or OCR fallback    → mix as needed
Level 3  is the resulting text trustworthy?         → if not, re-read with vision
```

Each level only engages the more expensive option when the cheaper one is insufficient: native text is free, OCR is cheap and per-page, vision is the last resort and only for documents whose text came out unusable.

### `parser="auto"` vs `parser="smart"` — the common confusion

They overlap on the easy cases (a clean native PDF → both read the text layer; a pure image → both OCR it) and **diverge on mixed PDFs**:

| | `parser="auto"` | `parser="smart"` |
|---|---|---|
| Decision unit | whole document | individual page |
| Based on | file type | actual page content |
| Scanned page *inside* a native PDF | ❌ sent to pdfplumber, comes back empty | ✅ that page is OCR'd |
| Emits OCR confidence | only when it picked tesseract (images) | yes, for every page it OCR'd |

Rule of thumb: `parser="auto"` is "pick the obvious tool for this file type"; `parser="smart"` is "this is a PDF and I'm not sure every page has text, so check each one." If your PDFs might be partly scanned, prefer `smart` — and because `smart` emits per-page OCR confidence, it is also the parser that feeds Level 3's escalation decision.

---

## 6. Parsers

Parsers convert raw documents into structured `Document` objects with pages, blocks, bounding boxes, and text. DocuFlow includes 4 local parsers and 3 cloud OCR parsers — all producing the same standardized output, so everything downstream (evidence, confidence, search) works identically regardless of which one you pick.

The default `parser="auto"` is source-aware — it picks a parser by file type. This is **Level 1** of the three "auto" mechanisms; see [The Levels of "auto"](#5b-the-levels-of-auto) for how it relates to the `smart` parser and `extraction_type="auto"`.

- PDF inputs use native PDF parsing (`pdfplumber`) for text extraction, or the **smart** parser in auto-escalation workflows (`extraction_type="auto"`).
- Image inputs use Tesseract OCR for text extraction, or are rendered directly for vision/hybrid extraction.
- Text-like inputs (`txt`, `md`, `html`, `csv`, `json`, `xml`, `eml`) are normalized by ingestion into a one-page parsed `Document`, so no parser is needed.
- Office and spreadsheet inputs route to Docling when that extra is installed.

### PdfplumberParser (`"pdfplumber"`)

Extracts embedded text directly from the PDF's internal text layer. Fast, accurate for digital PDFs, but returns empty text for scanned documents.

```python
pipeline = DocumentPipeline(parser="pdfplumber")
```

- **Speed**: ~100ms per document
- **Best for**: digitally-created PDFs, contracts, reports
- **Produces**: text blocks with bounding boxes, no confidence scores
- **Fails on**: scanned documents, image-only PDFs
- **Install**: `pip install docuflow[pdf]`

### TesseractParser (`"tesseract"`)

Renders PDF pages to images, then runs Tesseract OCR to extract text. Works on scanned documents. Produces per-word confidence scores.

```python
pipeline = DocumentPipeline(parser="tesseract")

# With custom config
from docuflow.parsing.tesseract_parser import TesseractParser
parser = TesseractParser(languages=["eng", "ita"], dpi=300, preprocess_steps=["denoise"])
pipeline = DocumentPipeline(parser=parser)
```

Parameters:
- `languages` — OCR languages (default: `["eng"]`). Use Tesseract language codes.
- `dpi` — rendering DPI (default: 200). Higher = better OCR but slower.
- `preprocess_steps` — image preprocessing before OCR. Options: `"grayscale"`, `"denoise"`, `"threshold"`, `"deskew"`.

- **Speed**: 1-5 seconds per page
- **Best for**: scanned documents, image-heavy PDFs
- **Produces**: word-level blocks with bounding boxes AND confidence scores (0-1)
- **Requires**: Tesseract binary installed on the system
- **Install**: `pip install docuflow[ocr]`

### DoclingParser (`"docling"`)

Uses IBM's Docling library for advanced document understanding. Detects layout structure (titles, paragraphs, tables, figures), reconstructs reading order, and handles complex formats.

```python
pipeline = DocumentPipeline(parser="docling")
```

- **Speed**: 4-5 seconds per page
- **Best for**: complex layouts, tables, multi-column documents, non-PDF formats
- **Produces**: semantic blocks (title, paragraph, table, formula, etc.) with bounding boxes
- **Formats**: PDF, DOCX, PPTX, XLSX, HTML, images
- **Table extraction**: 97.9% accuracy on complex tables — far better than pdfplumber/Tesseract
- **Install**: `pip install docuflow[docling]` (heavy — includes PyTorch)

### SmartParser (`"smart"`)

**Level 2** of the "auto" mechanisms (see [The Levels of "auto"](#5b-the-levels-of-auto)): unlike `parser="auto"`, which picks one parser for the whole file by type, `smart` decides per page. It first tries native text extraction (pdfplumber); for pages where that fails (scanned, sparse, garbled), it falls back to Tesseract OCR.

```python
pipeline = DocumentPipeline(parser="smart")

# Custom config
from docuflow.parsing.smart_parser import SmartParser
parser = SmartParser(ocr_languages=["eng", "fra"], dpi=300)
pipeline = DocumentPipeline(parser=parser)
```

Parameters:
- `ocr_languages` — languages for OCR fallback (default: `["eng"]`)
- `dpi` — rendering DPI for OCR pages (default: 200)
- `min_text_length` — minimum characters before a page is considered "good" (default: 20)

A page triggers OCR if:
- Text is shorter than 20 characters
- No text blocks exist
- Page has embedded images but little text
- More than 10% of characters are garbled (Unicode private-use area)

- **Speed**: fast for digital pages, slow only for pages that need OCR
- **Best for**: mixed documents where some pages are digital and some are scanned
- **Install**: `pip install docuflow[pdf,ocr]`

### Cloud OCR Parsers

Three managed OCR services plug in as parsers. They produce the same line-level blocks
with per-word confidences as Tesseract — higher accuracy, at a per-page API cost.

#### Azure Document Intelligence (`"azure-di"`)

```python
pipeline = DocumentPipeline(parser={"type": "azure-di", "model": "prebuilt-read"})
```

Sends the file natively (PDF, images, Office formats) — no local rendering. Credentials
via `endpoint`/`key` config keys or the `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` /
`AZURE_DOCUMENT_INTELLIGENCE_KEY` environment variables.
**Install**: `pip install docuflow[azure]`

#### AWS Textract (`"textract"`)

```python
pipeline = DocumentPipeline(parser={"type": "textract", "region": "eu-west-1"})
```

Renders pages locally and calls the synchronous DetectDocumentText API per page —
**no S3 bucket required**. Credentials via the standard boto3 chain (env vars, profile,
IAM role). **Install**: `pip install docuflow[aws,pdf]`

#### Google Document AI (`"google-docai"`)

```python
pipeline = DocumentPipeline(
    parser={"type": "google-docai", "project": "my-project", "processor_id": "abc123"}
)
```

Sends the file natively to a Document AI OCR processor. Configuration via config keys
or `GOOGLE_DOCAI_PROJECT` / `GOOGLE_DOCAI_LOCATION` / `GOOGLE_DOCAI_PROCESSOR_ID`;
authentication via Google application default credentials.
**Install**: `pip install docuflow[gcp]`

### Comparison Table

| Feature | pdfplumber | Tesseract | Docling | Smart | azure-di | textract | google-docai |
|---------|---------|-----------|---------|-------|----------|----------|--------------|
| Digital PDFs | Excellent | Good | Excellent | Excellent | Excellent | Good | Excellent |
| Scanned PDFs | Fails | Good | Good | Good | Excellent | Excellent | Excellent |
| Speed | ~100ms | 1-5s/page | 4-5s/page | Varies | API call | API call/page | API call |
| Cost | Free | Free | Free | Free | Per page | Per page | Per page |
| Bounding boxes | Yes (word) | Yes (word) | Yes | Yes | Yes (word) | Yes (word) | Yes (word) |
| Per-word confidence | No | Yes (0-1) | When OCR fires | Per page | Yes (0-1) | Yes (0-1) | Yes (0-1) |
| Table extraction | Basic | Basic | Excellent | Per page | Basic | Basic | Basic |
| Non-PDF formats | No | No | Yes | No | Yes | Images | Yes |
| Runs locally | Yes | Yes | Yes | Yes | No | No | No |

### Coordinate Convention

Every parser emits bounding boxes in **one canonical coordinate space: top-left origin,
PDF points (72 per inch)** — recorded as `page.unit == "pt"`. OCR parsers convert their
rendered-pixel coordinates via the rendering DPI; Azure DI converts inches. The one
exception is Google Document AI on pixel inputs, where the physical page size is unknown:
those pages keep `unit="px"`, still internally consistent with `page.width`/`page.height`.

To overlay any bbox on a page rendered at any DPI, use relative coordinates:

```python
rel = bbox.to_relative(page.width, page.height)   # 0-1 coords
# pixel rect = rel * rendered_image_size — works for every parser
```

### Using a Custom Parser

Any object implementing the `Parser` protocol works:

```python
from docuflow.parsing.base import Parser
from docuflow.documents.models import Document

class MyParser:
    async def parse(self, document: Document) -> Document:
        # Your parsing logic
        document.pages = [...]
        document.raw_text = "..."
        document.status = "parsed"
        return document

pipeline = DocumentPipeline(parser=MyParser())
```

---

## 6b. Structured Tables

When using the Docling parser, tables are extracted as first-class structured objects — not flattened text. Each table preserves its cell grid, row/column headers, spans, and per-cell bounding boxes.

### The Table and Cell Models

```python
from docuflow.documents.tables import Table, Cell

# After parsing with Docling
pipeline = DocumentPipeline(parser="docling")
result = pipeline.run_sync("financial_report.pdf", schema=FinancialData)

# Access tables from parsed pages
for page in result.pages:  # (via pipeline state, not ExtractionResult)
    for table in page.tables:
        print(f"Table: {table.num_rows}x{table.num_cols}")
```

### Cell — Every Cell Knows Its Headers

The key differentiator: each data cell carries resolved `row_headers` and `col_headers` — the actual header text, not just indices. A cell can answer "I am the value at Revenue × Q3 2024."

```python
cell = table.cell_at(1, 1)
cell.text              # "4,200"
cell.row, cell.col     # 1, 1
cell.row_span          # 1 (or more for merged cells)
cell.col_span          # 1
cell.is_column_header  # False
cell.is_row_header     # False
cell.row_headers       # ["Revenue"]   — which row this belongs to
cell.col_headers       # ["Q3 2024"]   — which column this belongs to
cell.bbox              # BoundingBox for this specific cell
```

### Table Navigation

```python
# Header rows
for row in table.header_rows:
    print([cell.text for cell in row])
# ["", "Q3 2024", "Q3 2023"]

# Data rows (excludes headers)
for row in table.data_rows:
    print([cell.text for cell in row])
# ["Revenue", "4,200", "3,800"]
# ["Cost", "2,100", "1,900"]

# Access by position (handles spans)
table.cell_at(1, 1)        # Cell at row 1, col 1
table.column_values(1)     # All data cells in column 1
table.row_values(1)        # All cells in row 1

# Convert to list of dicts (like pandas records)
records = table.to_dict_records()
# [{"Q3 2024": "4,200", "Q3 2023": "3,800"}, {"Q3 2024": "2,100", "Q3 2023": "1,900"}]
```

### Which Parsers Produce Tables?

| Parser | `page.tables` | Table quality |
|--------|--------------|---------------|
| Docling | Structured `Table` objects | Full cells, headers, spans, bboxes |
| pdfplumber | Empty `[]` | Tables appear as text blocks |
| Tesseract | Empty `[]` | Tables appear as OCR'd text |
| Smart | Empty `[]` | Tables appear as text blocks |

Only Docling produces structured tables. Other parsers include table content in their text blocks — the LLM can still read markdown tables, but you don't get cell-level structure.

### How Tables Reach the LLM

Tables are sent to the LLM as markdown (Docling's `export_to_markdown()`), which LLMs read well. The structured `Table`/`Cell` objects are available for:
- **Evidence matching** — match extracted values to specific cells with bboxes
- **Post-extraction validation** — verify subtotals add up
- **Direct access** — skip the LLM for simple table lookups
- **Cell-level highlighting** — show exactly which cell a value came from in a review UI

---

## 7. Extraction Engines

After parsing, the extraction engine sends the document content to an LLM and gets back structured data matching your schema.

### Extraction Types

DocuFlow has 4 extraction types: `text`, `vision`, and `hybrid` each use a fixed approach to read the document, while `auto` adaptively escalates from text to vision based on measured OCR quality (it is Level 3 of [The Levels of "auto"](#5b-the-levels-of-auto)).

### Choosing the right PDF strategy

Pick the simplest strategy that matches the document quality, then add more machinery only when the input justifies it:

- **Digital PDFs with clean text**: use `parser="pdfplumber"` and `extraction_type="text"`. This is the fastest and usually the most accurate when the text layer is reliable.
- **Scanned PDFs or image-heavy pages**: use `parser="tesseract"` or a cloud OCR parser. OCR gives you confidence scores and works when there is no text layer.
- **Mixed document streams**: use `parser="smart"`. It reads native text where possible and falls back to OCR only on pages that need it.
- **Visually complex documents**: use `parser=None` with `extraction_type="vision"`. The model reads page images directly and can interpret layout, stamps, tables, and visual context.
- **Very ambiguous or high-value documents**: use `extraction_type="hybrid"` to combine text and vision candidates, then let a decider choose the strongest field values.
- **Variable-quality batches**: use `extraction_type="auto"` with the default `parser="auto"`. Start cheap and escalate PDF/image inputs to vision only when OCR quality is poor.
- **Text, email, CSV, JSON, XML, or Markdown files**: use the default `parser="auto"` with `extraction_type="text"`. Ingestion converts them into a one-page parsed `Document`, so no OCR or PDF parser is required.
- **Images**: use the default `parser="auto"` for OCR-backed text extraction, or use `extraction_type="vision"`/`"hybrid"` when the visual layout matters.
- **Office/spreadsheet files**: use the default `parser="auto"` with `docuflow[docling]` installed, or explicitly choose `parser="docling"`.
- **Important documents**: add `extraction_mode="multi"` so independent candidates can agree or disagree before a final answer is accepted.
- **Weak fields**: enable `verification` so low-confidence values get a zoomed re-read instead of relying on the original extraction alone.

Rule of thumb:

- clean digital PDF -> `pdfplumber`
- scanned PDF -> `tesseract` or cloud OCR
- mixed batch -> `smart`
- complex layout -> `vision` or `hybrid`
- text-like file -> parserless ingestion via `auto`
- Office/spreadsheet -> `docling`
- highest accuracy -> `multi` + `verification`

#### Text Extraction (`extraction_type="text"`)

The parser produces text → the LLM reads that text. This is the default.

```python
pipeline = DocumentPipeline(
    parser="auto",              # or "pdfplumber", "tesseract", "docling", "smart"
    extraction_type="text",     # default
)
```

Pipeline: `Ingest → Parse? → Extract`

The LLM receives the document text organized by page, plus the schema definition and an example of the expected output format.

#### Vision Extraction (`extraction_type="vision"`)

Pages are rendered as images and sent directly to a vision-capable LLM. No parser needed — the LLM reads the document visually.

```python
pipeline = DocumentPipeline(
    parser=None,                # no parser — vision reads images directly
    extraction_type="vision",
    model="openai/gpt-4o",     # must be a vision-capable model
)
```

Pipeline: `Ingest → ExtractVision`

Internally, the vision engine:
1. Renders all pages to PNG images at the configured DPI
2. Runs Tesseract OCR on those same images (automatically, for evidence grounding)
3. Encodes images as base64 and sends them to the LLM with the schema
4. Matches LLM evidence against OCR blocks for bounding boxes

This means vision extraction produces the same rich evidence (bboxes, block IDs, OCR confidence) as text extraction — even though the LLM read images, not text.

**Important**: `parser` must be `None` when using vision. If you set a parser, DocuFlow raises a `ValueError` at pipeline construction.

#### Hybrid Extraction (`extraction_type="hybrid"`)

Runs both vision and text agents in parallel for maximum diversity, then a vision-capable decider reviews all candidates against the actual page images.

```python
pipeline = DocumentPipeline(
    parser=None,
    extraction_type="hybrid",
    n_instances=2,              # 2 vision + 2 text + 1 decider = 5 LLM calls
)
```

Pipeline: `Ingest → ExtractHybrid`

How it works:
1. Render pages to images + run Tesseract OCR (once, shared)
2. N vision LLM calls (page images → LLM) at varied temperatures
3. N text LLM calls (OCR markdown → LLM) at varied temperatures
4. 1 vision decider call: receives ALL candidates (labelled "vision" or "text") + page images, picks the best value per field

The decider can actually look at the document to break ties — it's not just a majority vote.

#### Auto Extraction (`extraction_type="auto"`)

**Level 3** of the "auto" mechanisms (see [The Levels of "auto"](#5b-the-levels-of-auto)).
Unlike `parser="auto"` (which picks a parser by file type) and `parser="smart"` (which
picks native-vs-OCR per page), this operates *after* parsing and decides the extraction
**modality**: keep the cheap text path, or re-read the document with a vision LLM.

Text extraction with **automatic vision escalation** — for document streams where most
files are fine but some are extremely unstructured (handwriting, stamps, crumpled photos,
low-quality scans) and OCR quietly produces garbage.

```python
pipeline = DocumentPipeline(
    extraction_type="auto",
    escalation={"min_ocr_score": 0.6, "escalate_to": "vision"},
)
```

How it works — three tiers, each engaged only when the cheaper one fails:

```
Tier 1: native text layer (pdfplumber)      — free
Tier 2: OCR for pages that need it (smart)  — cheap
Tier 3: OCR quality too poor → re-read the  — vision LLM
        original file with vision/hybrid
```

The key insight: OCR **fails confidently** — on a bad input it doesn't error, it returns
plausible garbage, and a text LLM will happily extract wrong values from it. Auto mode
uses the OCR confidence scores as a quality gate after parsing. The document escalates
to vision when:

- the document's mean OCR confidence is below `min_ocr_score` (default 0.6), or
- more than `max_low_confidence_ratio` of words are low-confidence (default 40%), or
- there is almost no text at all (below `min_chars_per_page`, default 20) — neither the
  text layer nor OCR produced anything usable

Escalated results are marked so the (more expensive) vision call is always visible:

```python
result.escalated           # True if the document was re-read by the vision LLM
result.escalation_reason   # e.g. "OCR confidence 0.42 below threshold 0.6"
result.usage               # the actual token cost, escalated or not
```

`escalate_to: "hybrid"` escalates to hybrid extraction instead of plain vision.
Auto mode implies the smart parser unless you explicitly configure an OCR parser
(tesseract or a cloud OCR) yourself.

**Privacy interaction**: vision sends raw page images to the LLM, bypassing text
anonymization. When a `PrivacyPolicy` is configured, escalation is therefore suppressed
(the pipeline stays on the anonymized text path) and a `vision_escalation_suppressed`
trace event records that it would have escalated.

In YAML:

```yaml
extraction_type: auto
escalation:
  min_ocr_score: 0.6
  max_low_confidence_ratio: 0.4
  escalate_to: vision
```

#### Zoom-and-Verify (`verification=`)

Confidence scores tell you *which* fields are weak — zoom-and-verify does something
about it, surgically. After extraction, each weak field (low consensus, low OCR span
score, or a value OCR couldn't locate) gets one targeted vision call: its page is
rendered at high DPI (default 300), cropped to the field's highlight rect plus padding,
and the model answers a focused question about just that region — where 0/O, 1/l/7 and
5/S are actually distinguishable.

```python
pipeline = DocumentPipeline(
    extraction_mode="multi",
    verification={"trigger_consensus_below": 0.7, "trigger_ocr_below": 0.6},
)
result = pipeline.run_sync("claim_form.pdf", schema=InsuranceClaim)

f = result.fields["total"]
f.verification.reason          # "OCR span confidence 0.42 below 0.6"
f.verification.agrees          # the re-read confirmed the value
f.verification.changed         # or: a correction was applied
f.verification.original_value  # always preserved when changed
```

Outcomes:

- **Confirmed** (`agrees=True`): the zoomed re-read matches → the field trust gate is opened and the value may be accepted.
- **Corrected** (`changed=True`): the re-read differs *and* the new value passes schema
  validation → value replaced, original preserved, and the trust gate stays aligned with the verified value.
- **Rejected**: a correction that fails schema validation is recorded but never applied.
- **Unreadable**: the model couldn't read the region → field untouched, `verified=False`.

Cost is capped (`max_fields`, default 5) and every verification call's tokens are merged
into `result.usage`. In YAML:

```yaml
verification:
  trigger_consensus_below: 0.7
  trigger_ocr_below: 0.6
  max_fields: 5
```

Requires a vision-capable model (the same adapter used for extraction).

### Extraction Modes

Each extraction type supports two modes:

#### Single Mode (`extraction_mode="single"`)

One LLM call. Fast, cheap, good for most documents.

```python
pipeline = DocumentPipeline(extraction_mode="single")  # default
```

#### Multi-Agent Mode (`extraction_mode="multi"`)

N parallel LLM calls at different temperatures for diversity, then a decider picks the best answer per field.

```python
pipeline = DocumentPipeline(
    extraction_mode="multi",
    n_instances=3,              # 3 parallel calls + 1 decider = 4 LLM calls
)
```

Parameters:
- `n_instances` — number of parallel extraction calls (default: 5)
- `temperatures` — optional list of floats (one per instance). If not provided, auto-generated with a spread around 0.3.

The decider:
- Compares all candidate extractions field by field
- Picks the most consistent value per field
- Prefers values with stronger evidence
- Sets confidence based on agreement (1.0 if all agree, 0.7 if majority, 0.4 if split)


**Consensus short-circuit:** the decider only runs when it can add something — when
candidates disagree. If all N candidates produce identical values for every field
(the common case on clean documents), the decider call is skipped entirely: one less
LLM round trip (~half the multi-mode latency) and its tokens saved. Consensus scores
are computed identically either way; a `decider_skipped` trace event records it.

### Summary Table

| extraction_type | extraction_mode | Parser needed? | LLM calls | Best for |
|----------------|----------------|---------------|-----------|----------|
| text | single | Yes | 1 | Simple digital PDFs |
| text | multi | Yes | N+1 | Important documents |
| vision | single | No | 1 | Complex layouts, forms |
| vision | multi | No | N+1 | High-value visual docs |
| hybrid | (always multi) | No | 2N+1 | Critical documents |
| auto | single or multi | Yes (smart) | text cost, + vision only on escalation | Mixed-quality document streams |

### Confidence Scores — Two Independent Signals

DocuFlow does NOT use the LLM's self-reported confidence. Models can't reliably know when
they're wrong — they'll report high confidence on hallucinations. Instead, every extraction
carries **two separate, independently-computed scores**, each answering a different question:

| | **OCR confidence** | **LLM consensus** |
|---|---|---|
| Question it answers | Did we **read** the characters on the page correctly? | Did independent LLM runs **interpret** the document the same way? |
| Layer it measures | Perception — the actual data extraction from pixels (the parser/OCR layer) | Reasoning — the LLM's mapping of text/images to your schema fields |
| Where it comes from | The OCR engine's per-word recognition scores (Tesseract, Azure DI, Textract, Google DocAI) | Agreement across N parallel LLM instances in multi/hybrid mode |
| When it exists | Only when an OCR-based parser ran. Native parsing (pdfplumber on a digital PDF) reads the text layer directly — there is nothing to "mis-read", so there is no OCR score | Only when more than one instance ran. A single LLM call has nothing to agree with |
| When it's the signal that matters | Scanned/photographed documents, where a `7` can be read as a `1` | **Vision and hybrid extraction, where there may be no parser at all** — the LLM reads page images directly, so consensus is the primary trust signal |

The two are deliberately **not blended into one number**. A field can have perfect OCR
(the characters are crisp) but split consensus (the LLMs disagree about *which* number is
the total) — or unanimous consensus on text that OCR read poorly. Those are different
problems with different fixes, and a single blended score would hide which one you have.

Neither score ever breaks the pipeline: when a score is not applicable it is `None`,
not zero — "we don't know" is different from "we know it's bad".

#### OCR confidence — document level and field level

```python
result.ocr                        # OCRDocumentConfidence | None
result.ocr.score                  # 0-1 — mean word confidence across the document
result.ocr.word_count             # how many recognized words contributed
result.ocr.low_confidence_ratio   # fraction of words below 0.6

field = result.fields["total"]
field.ocr                         # OCRFieldConfidence | None
field.ocr.score                   # min word confidence of the matched span —
                                  #   a field is only as trustworthy as its worst word
field.ocr.match_method            # "exact_block" | "fuzzy_block" | "page_text" | "unmatched"
field.ocr.match_ratio             # 1.0 = exact match, <1.0 = fuzzy match quality
field.ocr.matched_text            # the source text the value was matched to
field.ocr.bbox                    # highlight rect of the scored span
```

The field-level score is computed by **matching the extracted value back** to the OCR
words: the LLM's evidence quote is tried first, then the value itself; exact match first,
then fuzzy matching (for OCR-garbled text like `INV-O01` vs `INV-001`), with currency and
case normalization. `"unmatched"` means OCR ran but the value couldn't be located — common
for reformatted dates or anonymized values, and honestly reported rather than guessed.

#### LLM consensus — agreement across instances

```python
field.consensus                   # FieldConsensus | None (None in single mode)
field.consensus.agreement         # "4/5" — candidates agreeing with the FINAL value
field.consensus.agreement_ratio   # 0.8
field.consensus.majority_ratio    # size of the largest candidate cluster
field.consensus.n_instances       # instances launched
field.consensus.n_succeeded       # instances that returned valid JSON
```

A subtlety worth knowing: `agreement_ratio` measures agreement with the **final value
chosen by the decider**, not just the internal majority. The decider is allowed to pick a
minority answer when it has stronger evidence — when that happens,
`agreement_ratio < majority_ratio`, which tells a reviewer "the decider overrode the
majority here, look closely."

#### Availability matrix

| Setup | OCR confidence | LLM consensus |
|-------|---------------|---------------|
| pdfplumber + single | — | — |
| pdfplumber + multi | — | Yes |
| tesseract / cloud OCR + single | Yes | — |
| tesseract / cloud OCR + multi | Yes | Yes |
| smart | Per page (only OCR'd pages) | Per mode |
| vision (no parser) | Yes (internal OCR enrichment) | Per mode |
| hybrid (no parser) | Yes (internal OCR enrichment) | Yes (always multi) |

### Trust Gate

The field-level `trust` object carries the accept/review decision combining agreement
with **source verification** (does the extracted value exist in the document text at
all — the hallucination check). Every field gets a `trust` object and a direct boolean
`trust_gate` convenience property:

```python
field = result.fields["total"]
field.trust.agreement        # "3/3" — all runs agreed
field.trust.found_in_source  # True — value exists in document text
field.trust.valid            # True — passes basic checks
field.trust.trust_gate       # True — safe to skip review
field.trust_gate             # same boolean gate on the field itself
field.trust.explanation      # "Agreement: 3/3; Found in source: True; Auto-accept: yes"
```

**The decision is nearly binary:**
- **Passes trust gate** (`trust_gate = True`): all runs agree AND value found in source AND valid → skip review
- **Fails trust gate** (`trust_gate = False`): anything else → human should look

| Extraction mode | What agreement looks like |
|----------------|--------------------------|
| single (1 call) | Always "1/1" — trust depends on source verification only |
| multi (3 calls) | "3/3" (unanimous), "2/3" (split), "1/3" (all different) |
| hybrid (2+2 calls) | "4/4", "3/4", etc. — cross-approach agreement is the strongest signal |

For new code, prefer the explicit `field.ocr` and `field.consensus` scores described above, and use `field.trust_gate` for the accept/review decision.

### JSON Reliability

All LLM calls enforce reliable JSON output through 4 mechanisms:

1. **JSON mode** — `response_format={"type": "json_object"}` is passed to every LLM call
2. **Concrete example** — the prompt includes a filled-out example using the actual field names from your schema
3. **Markdown fence stripping** — if the LLM wraps JSON in code fences, they're stripped
4. **Auto-retry** — if JSON parsing fails, a repair message is sent with JSON mode enforced

### Domain Context

Provide industry-specific context to improve extraction accuracy:

```python
pipeline = DocumentPipeline(
    context=(
        "You work in motor insurance claims processing. "
        "Documents are accident claim forms and repair invoices. "
        "Dates should be in DD-MM-YYYY format. "
        "Policy numbers follow the pattern POL-XXXXXXX."
    ),
)
```

The context is appended to the LLM system prompt as a "Domain context" section. It works across all extraction types and modes.

### Token Usage & Cost

Every result reports the aggregated LLM token usage that produced it — summed across
**all** calls: multi-instance candidates, the decider, JSON-repair retries, and LLM
reviewers.

```python
result.usage                    # TokenUsage | None
result.usage.prompt_tokens      # e.g. 6200
result.usage.completion_tokens  # e.g. 480
result.usage.total_tokens
result.usage.n_llm_calls        # e.g. 4 in multi mode (3 instances + decider)
result.usage.cost_usd           # litellm-priced estimate; None if the model is unpriced
```

`usage` is `None` when the adapter reports no usage information. Batch processing
aggregates it too: `report.usage` sums tokens, calls and cost across the whole batch.
The `/extract` HTTP endpoint and the CLI JSON output include it automatically.

### Schema Sharding (`schema_shards=`)

For wide schemas (25+ fields), generation time dominates — the LLM writes the output
tokens serially. Sharding splits the schema into K contiguous field groups extracted
**in parallel**, then merges the results (fields, evidence, confidence scores, token
usage) back into one result for the full schema:

```python
pipeline = DocumentPipeline(schema_shards=3)   # or schema_shards: 3 in YAML
```

Trade-offs, honestly: the document text is sent K times (input cost multiplies), and
fields split across shards lose cross-field coherence — the LLM extracting `total`
no longer sees `line_items`. Use it for wide, flat schemas where fields are
independent; keep related fields adjacent in the schema definition, since shards are
contiguous groups. Text extraction only (vision/hybrid would multiply the much larger
image cost). A `schema_sharding` trace event records the split.

### Prompt Caching

For batches sharing one workflow, the system prompt + schema prefix repeats on every
call. Anthropic models cache it explicitly (opt-in); OpenAI caches automatically:

```python
pipeline = DocumentPipeline(
    model="anthropic/claude-sonnet-4-6",
    llm_kwargs={"prompt_caching": True},
)
```

This is mostly a cost win (cached prefix tokens are billed at a fraction) with a
modest time-to-first-token improvement.

### LLM Providers

DocuFlow uses litellm under the hood, which supports 100+ LLM providers. The `model` parameter uses litellm's format:

```python
# OpenAI
pipeline = DocumentPipeline(model="openai/gpt-4o")
pipeline = DocumentPipeline(model="openai/gpt-4o-mini")

# Anthropic
pipeline = DocumentPipeline(model="anthropic/claude-sonnet-4-20250514")

# Google Gemini
pipeline = DocumentPipeline(model="gemini/gemini-2.0-flash")

# Azure OpenAI
pipeline = DocumentPipeline(model="azure/my-deployment")

# Local models (via Ollama)
pipeline = DocumentPipeline(model="ollama/llama3")
```

Set your API key via environment variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) or pass it directly:

```python
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter
llm = LiteLLMAdapter(model="openai/gpt-4o", api_key="sk-...")
pipeline = DocumentPipeline(parser="auto")
# Use manual Pipeline with Extract(llm=llm) for custom LLM instances
```

---

## 8. The Pipeline

### Three Ways to Build a Pipeline

#### 1. `extract()` — One-liner

```python
from docuflow import extract

result = extract(
    "invoice.pdf",
    schema=Invoice,
    model="openai/gpt-4o",
    parser="auto",
    storage="local",
    privacy=PrivacyPolicy(...),
)
```

Creates a `DocumentPipeline` internally, runs it once, returns the result.

#### 2. `DocumentPipeline` — Configurable, Reusable

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="smart",
    model="openai/gpt-4o",
    storage="local",
    validators=[RequiredFields(["total"])],
    review_rules=[OverallConfidenceBelow(0.7)],
    privacy=PrivacyPolicy(provider=PresidioProvider()),
    extraction_mode="multi",
    extraction_type="text",
    n_instances=3,
    context="You work in insurance claims processing.",
)

# Reuse for multiple documents
result1 = pipeline.run_sync("claim1.pdf", schema=ClaimSchema)
result2 = pipeline.run_sync("claim2.pdf", schema=ClaimSchema)
```

All parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parser` | str or Parser | `"auto"` | `"auto"`, `"pdfplumber"`, `"tesseract"`, `"docling"`, `"smart"`, `"azure-di"`, `"textract"`, `"google-docai"`, `None` |
| `model` | str | `"openai/gpt-4o"` | LLM model (litellm format) |
| `storage` | str or Storage | `None` | `None`, `"local"`, or Storage instance |
| `validators` | list | `None` | List of Validator instances |
| `review_rules` | list | `None` | List of ReviewRule or LLMReviewer instances |
| `escalation` | dict | `None` | Auto-mode escalation thresholds (see Auto Extraction) |
| `verification` | dict | `None` | Zoom-and-verify thresholds (see Zoom-and-Verify) |
| `schema_shards` | int | `None` | Split wide schemas into K parallel extractions (see Schema Sharding) |
| `privacy` | PrivacyPolicy | `None` | Privacy/anonymization config |
| `extraction_mode` | str | `"single"` | `"single"` or `"multi"` |
| `extraction_type` | str | `"text"` | `"text"`, `"vision"`, or `"hybrid"` |
| `n_instances` | int | `5` | Number of parallel LLM calls (multi mode) |
| `temperatures` | list[float] | `None` | Custom temperature per instance |
| `vision_dpi` | int | `200` | DPI for page rendering |
| `context` | str | `None` | Domain context for LLM prompt |

#### 3. Manual `Pipeline` — Full Control

Build your own step sequence:

```python
from docuflow.workflow import (
    Pipeline, Ingest, Parse, Extract, ExtractVision, ExtractHybrid,
    Anonymize, Validate, Review, Store,
)
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter
from docuflow.storage.local import LocalDocumentStore

llm = LiteLLMAdapter(model="openai/gpt-4o")

pipeline = Pipeline([
    Ingest(path="invoice.pdf"),
    Parse(parser="tesseract"),
    Anonymize(policy=PrivacyPolicy(provider=PresidioProvider())),
    Extract(schema=Invoice, llm=llm, mode="multi", n_instances=3, context="Insurance"),
    Validate(validators=[RequiredFields(["total"]), EvidenceRequired()]),
    Review(rules=[OverallConfidenceBelow(0.7), my_llm_reviewer]),
    Store(storage=LocalDocumentStore("./output")),
])

result = pipeline.run_sync()
print(result.success)
print(result.state.extraction_result.data)
```

### Pipeline Steps Reference

| Step | Name | Purpose |
|------|------|---------|
| `Ingest(path)` | ingest | Load file, create Document with metadata |
| `Parse(parser)` | parse | Extract text and blocks from document |
| `Anonymize(policy)` | anonymize | Detect and mask PII before extraction |
| `Extract(schema, llm, ...)` | extract | Send text to LLM, get structured data |
| `ExtractVision(schema, llm, ...)` | extract_vision | Send page images to vision LLM |
| `ExtractHybrid(schema, llm, ...)` | extract_hybrid | Vision + text agents in parallel |
| `FillForm(data, output_path, ...)` | fill_form | Write trusted data into a PDF form, returning `FillingResult` |
| `Validate(validators)` | validate | Check fields against rules |
| `Review(rules)` | review | Flag documents for human review |
| `Store(storage)` | store | Persist document, result, and trace |

### Pipeline Failure Behavior

When a step fails:
1. The error is recorded in `state.errors`
2. The pipeline stops (no subsequent steps run)
3. If storage is configured, partial state is saved automatically
4. `DocumentPipeline` raises `WorkflowError` with the full result attached

```python
from docuflow.errors import WorkflowError

try:
    result = pipeline.run_sync("bad_file.pdf", schema=Invoice)
except WorkflowError as e:
    print(e.result.errors)             # ["Step 'extract' failed: ..."]
    print(e.result.state.current_step) # "extract"
    print(e.result.state.document)     # Document (if ingestion succeeded)
    print(e.result.trace.events)       # all events up to failure
```

---

## 9. Validation

Validation checks extraction results against rules and updates field statuses.

### Built-in Validators

```python
from docuflow.validation import RequiredFields, EvidenceRequired, TypeValidation, CustomRule

pipeline = DocumentPipeline(
    validators=[
        RequiredFields(["supplier_name", "total", "invoice_number"]),
        EvidenceRequired(["total", "supplier_name"]),
        TypeValidation(),
    ],
)
```

| Validator | Parameters | What it checks |
|-----------|-----------|----------------|
| `RequiredFields(fields)` | `fields: list[str]` | Fields must exist and have non-None values |
| `EvidenceRequired(fields)` | `fields: list[str] \| None` | Fields must have at least one Evidence object |
| `TypeValidation()` | (none) | Warns on empty string values |
| `CustomRule(name, fn)` | `name: str`, `fn: Callable` | User-defined validation function |

### Custom Validation Rules

```python
from docuflow.validation import CustomRule, ValidationError

def check_total_positive(result):
    errors = []
    total = result.fields.get("total")
    if total and total.value is not None and total.value < 0:
        errors.append(ValidationError(
            field_name="total",
            rule_name="positive_total",
            message="Total must be positive",
        ))
    return errors

pipeline = DocumentPipeline(
    validators=[CustomRule("positive_total", check_total_positive)],
)
```

### Validation Results

After validation, each field's `validation_status` is updated:
- `"valid"` — all rules passed
- `"warning"` — warning-level issues found
- `"error"` — error-level issues found

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)
for name, field in result.fields.items():
    print(f"{name}: {field.validation_status}")
    if field.errors:
        print(f"  Errors: {field.errors}")
```

---

## 10. Review

The Review step checks extraction results against configurable rules and LLM-powered reviewers. If any rule triggers, the document is flagged with `needs_review=True`.

### Review Rules

```python
from docuflow.review import (
    OverallConfidenceBelow,
    FieldConfidenceBelow,
    AnyFieldConfidenceBelow,
    HasValidationErrors,
    FieldMissing,
    NoEvidence,
)

pipeline = DocumentPipeline(
    review_rules=[
        OverallConfidenceBelow(0.7),
        FieldConfidenceBelow({"total": 0.8, "supplier_name": 0.7}),
        FieldMissing(["total", "invoice_number"]),
        HasValidationErrors(),
    ],
)
```

| Rule | Parameters | When it flags |
|------|-----------|---------------|
| `OverallConfidenceBelow(threshold)` | `threshold: float = 0.7` | Average confidence below threshold |
| `FieldConfidenceBelow(fields)` | `fields: dict[str, float]` | Any named field below its threshold |
| `AnyFieldConfidenceBelow(threshold)` | `threshold: float = 0.6` | Any single field below threshold |
| `HasValidationErrors()` | (none) | Validation step found errors |
| `FieldMissing(fields)` | `fields: list[str]` | Critical fields are None or absent |
| `NoEvidence(fields)` | `fields: list[str] \| None` | Fields have no supporting evidence |

### LLM Reviewer

Create prompt-driven reviewers that use an LLM to inspect the extraction:

```python
from docuflow.review import LLMReviewer
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

llm = LiteLLMAdapter(model="openai/gpt-4o")

auditor = LLMReviewer(
    name="financial_auditor",
    prompt="Check if the extracted totals, VAT, and line items are mathematically consistent. Flag any discrepancies.",
    llm=llm,
)

compliance = LLMReviewer(
    name="compliance_check",
    prompt="Check if any extracted field contains PII that should not be stored. Flag any concerns.",
    llm=llm,
)

pipeline = DocumentPipeline(
    review_rules=[
        OverallConfidenceBelow(0.7),  # fast rule
        auditor,                       # LLM reviewer
        compliance,                    # LLM reviewer
    ],
)
```

Rules and reviewers mix freely. Rules are fast (no LLM call), reviewers are thorough (one LLM call each).

### Review Verdicts

Each LLM reviewer produces a `ReviewVerdict` — always stored on the result, even if approved:

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)

for v in result.review_verdicts:
    print(f"{v.reviewer}: {v.verdict} — {v.reasoning}")
# financial_auditor: Approved — Math checks out
# compliance_check: Not Approved — PII found in supplier_name field

print(result.needs_review)    # True (compliance flagged it)
print(result.review_reasons)  # ["compliance_check: PII found in supplier_name field"]
```

---

## 11. Human Corrections & Approval

### Correcting Fields

After review, humans can correct extracted values with a full audit trail:

```python
result.correct_field(
    "total", 1235.00,
    corrected_by="john@company.com",
    reason="OCR misread 5 as 6"
)

# The correction is tracked
print(result.fields["total"].value)           # 1235.00 (corrected)
print(result.fields["total"].original_value)  # 1234.56 (always preserved)
print(result.fields["total"].corrected)       # True
print(result.data["total"])                   # 1235.00 (data dict updated too)
```

Multiple corrections on the same field stack in the audit trail. The `original_value` always points to what the LLM originally extracted — it's never overwritten.

```python
for c in result.corrections:
    print(f"{c.field_name}: {c.old_value} → {c.new_value}")
    print(f"  By: {c.corrected_by}, Reason: {c.reason}")
    print(f"  At: {c.timestamp}")
```

### Approve / Reject

```python
# Approve
result.approve(approved_by="john@company.com")
print(result.review_status)  # "approved"
print(result.reviewed_by)    # "john@company.com"
print(result.reviewed_at)    # datetime

# Or reject
result.reject(rejected_by="john@company.com", reason="Wrong document type")
print(result.review_status)   # "rejected"
print(result.rejection_reason) # "Wrong document type"
```

Guards:
- Can't approve or reject twice (raises `ValueError`)
- Can't approve after rejection or vice versa

### Typical Workflow

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)

if result.needs_review:
    # Human looks at the result + evidence
    # Corrects any wrong fields
    result.correct_field("total", 1235.00, corrected_by="john", reason="OCR error")

    # Approves or rejects
    result.approve(approved_by="john")

# Save the final state (including corrections and approval)
from docuflow.storage.local import LocalDocumentStore
store = LocalDocumentStore("./output")
import asyncio
asyncio.run(store.save_result(result))
```

---

## 12. Provenance

Every field has a complete audit chain — one call gives you the full story from source PDF to approved value.

```python
prov = result.provenance()  # all fields
prov = result.provenance("total")  # single field

for field_name, p in prov.items():
    print(f"\n--- {field_name} ---")
    print(f"Value: {p.value}")
    print(f"Original value: {p.original_value}")
    print(f"Source text: {p.source_text!r}")
    print(f"Page: {p.page}")
    print(f"BBox: {p.bbox}")
    print(f"Block ID: {p.block_id}")
    print(f"Trust gate: {p.trust_gate}")
    print(f"Evidence confidence: {p.evidence_confidence}")
    print(f"Parser: {p.parser_name}")
    print(f"Model: {p.model_name}")
    print(f"Validation: {p.validation_status}")
    print(f"Review status: {p.review_status}")
    print(f"Reviewed by: {p.reviewed_by}")
    print(f"Review verdicts: {p.review_verdicts}")
    print(f"Corrected: {p.corrected}")
    print(f"Corrected by: {p.corrected_by}")
    print(f"Correction reason: {p.correction_reason}")
```

Provenance is a read-only view assembled from `ExtractionResult` and `ExtractedField` data. It serializes to JSON via `p.model_dump_json()`.

---

## 13. Privacy & Anonymization

The privacy module detects and anonymizes PII before document content reaches the LLM. It runs as a pipeline step between Parse and Extract.

### Basic Usage

```python
from docuflow import DocumentPipeline, PrivacyPolicy
from docuflow.privacy import PresidioProvider

pipeline = DocumentPipeline(
    parser="tesseract",
    privacy=PrivacyPolicy(
        provider=PresidioProvider(),
        mode="pseudonymize",
        reversible=True,
        fail_closed=True,
    ),
)
result = pipeline.run_sync("claim.pdf", schema=ClaimSchema)
```

### Anonymization Modes

| Mode | Example | Use case |
|------|---------|----------|
| `"redact"` | Mario Rossi → `[REDACTED]` | Maximum privacy, irreversible |
| `"mask"` | Mario Rossi → `M**** R****` | Partial masking for review UIs |
| `"pseudonymize"` | Mario Rossi → `PERSON_001` | LLM workflows (reversible, default) |
| `"hash"` | Mario Rossi → `a3f2c1...` | Duplicate detection |

### PrivacyPolicy Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `anonymize_before_llm` | bool | `True` | Anonymize before LLM calls |
| `mode` | AnonymizationMode | `"pseudonymize"` | How to replace PII |
| `reversible` | bool | `True` | Store mappings for restoration (pseudonymize only) |
| `provider` | PrivacyProvider | `None` | PII detection engine (e.g., PresidioProvider) |
| `entities` | list[str] | 7 common types | Which PII types to detect |
| `fail_closed` | bool | `True` | Stop pipeline if anonymization fails |
| `score_threshold` | float | `0.35` | Minimum detection confidence |
| `log_scrubbing` | bool | `True` | Remove PII from logs/traces |
| `mapping_store` | MappingStore | `None` | Where to store reversible mappings |

Default entities: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, `LOCATION`, `DATE_TIME`.

### Reversible Pseudonymization

When `reversible=True`, the same entity gets the same token within a document scope. Tokens can be restored after extraction.

```python
from docuflow.privacy import Anonymizer, PresidioProvider
from docuflow.privacy.mapping_store import LocalMappingStore

anonymizer = Anonymizer(PrivacyPolicy(
    provider=PresidioProvider(),
    mode="pseudonymize",
    reversible=True,
    mapping_store=LocalMappingStore("./mappings"),
))

# Anonymize
anon = await anonymizer.anonymize_text("John Doe sent email john@example.com")
print(anon.text)       # "PERSON_001 sent email EMAIL_ADDRESS_001"
print(anon.mapping_id) # UUID for this mapping

# Restore
restored = await anonymizer.restore_text(anon.text, anon.mapping_id)
print(restored)        # "John Doe sent email john@example.com"
```

### Fail-Closed Behavior

When `fail_closed=True` (default), if anonymization fails before an LLM call, the pipeline stops rather than sending raw PII to an external model.

### Image Redaction

For vision extraction, PII can be redacted from page images:

```python
from docuflow.privacy.image_redaction import ImageRedactor

redactor = ImageRedactor(provider=PresidioProvider())
redacted_image, findings = await redactor.redact_page_image(page_image)
# Black rectangles drawn over PII regions using OCR bounding boxes
```

### Trace Scrubbing

Remove PII from processing traces:

```python
from docuflow.privacy.scrubber import TraceScrubber

scrubber = TraceScrubber(provider=PresidioProvider())
clean_trace = await scrubber.scrub_trace(result_trace)
# PII replaced with [SCRUBBED] in all trace event metadata
```

---

## 14. Batch Processing

Process multiple documents and get a summary report.

```python
from docuflow import DocumentPipeline, process_batch

pipeline = DocumentPipeline(parser="smart", model="openai/gpt-4o")

report = process_batch(
    files=["inv1.pdf", "inv2.pdf", "inv3.pdf", ...],
    schema=Invoice,
    pipeline=pipeline,
    concurrency=5,  # max parallel extractions
)

# Summary
print(f"Total: {report.total}")
print(f"Succeeded: {report.succeeded}")
print(f"Failed: {report.failed}")
print(f"Needs review: {report.needs_review}")
print(f"Approved: {report.approved}")
print(f"Avg confidence: {report.average_confidence:.2f}")

# Top reasons for review
for reason, count in report.top_review_reasons.items():
    print(f"  {count}x {reason}")

# Per-document details
for doc in report.documents:
    print(f"{doc.file_name}: {'OK' if doc.success else 'FAILED'}")
    if doc.error:
        print(f"  Error: {doc.error}")
```

### Export to CSV

```python
csv_text = report.to_csv()
with open("results.csv", "w") as f:
    f.write(csv_text)

# Output columns: file_name, success, confidence, needs_review, <field1>, <field2>, ...
```

### Export to DataFrame

```python
df = report.to_dataframe()  # requires pandas
print(df[df["needs_review"] == True])
df.to_excel("results.xlsx")
```

---

## 14b. Routing Mixed Document Streams

Real inboxes are mixed: invoices, claim forms and contracts arrive together, each
needing a different workflow. The `WorkflowRouter` classifies each document with one
cheap LLM call and runs the matching registered workflow — documents that match
nothing land in `unclassified` with the classifier's reason, never force-extracted
with the wrong schema.

```python
from docuflow import WorkflowRouter

router = WorkflowRouter()                      # classifier model: gemini/gemini-2.5-flash
router.register("invoice", "workflows/invoices.yaml")
router.register("claim", "workflows/claims.yaml",
                description="motor insurance claim forms with policy numbers")

report = router.route_sync(["inbox/a.pdf", "inbox/b.pdf"], concurrency=5)

report.by_workflow["invoice"]   # results grouped per workflow
report.unclassified             # files that matched nothing, with the reason
report.failed                   # classified but extraction errored
report.usage                    # tokens/cost including the classification calls
report.to_csv()
```

How classification works: the router peeks at the first page (text layer; falls back
to a low-DPI page image for scans) and asks the classifier model to pick among the
registered names + descriptions. Below `confidence_threshold` (default 0.5) the
document goes to `unclassified` rather than guessing. Each routed result records the
classification decision, confidence and reason for auditability.

Registration accepts YAML workflow configs (path or dict) or explicit
`pipeline=` + `schema=` pairs.

### The `description` is the routing signal

The `description` string you pass to `register()` is **the exact text the classifier
LLM reads** when deciding which workflow a document belongs to. It is not metadata —
it is the prompt. A vague description produces unreliable routing; a precise one
produces reliable routing.

**Write descriptions for a classifier that knows nothing about your business:**

```python
# Too vague — "invoice" could be anything
router.register("invoice", pipeline=..., schema=Invoice,
                description="invoices")

# Clear and discriminative — includes AND excludes
router.register("invoice", pipeline=..., schema=Invoice,
                description="supplier invoices with line items and totals; "
                            "NOT repair quotes or credit notes")

router.register("claim", pipeline=..., schema=Claim,
                description="motor or property insurance claim forms "
                            "with policy number and damage amount")

router.register("contract", pipeline=..., schema=Contract,
                description="service or vendor contracts with parties, "
                            "term dates and payment clauses; NOT purchase orders")
```

Good description patterns:
- **State what the document is** — "supplier invoices", "motor insurance claim forms"
- **State key fields** — "with policy number and damage amount" — these are textual
  landmarks the classifier will spot in the document's first page
- **Exclude near-neighbours** with `NOT` — "NOT repair quotes" prevents the most
  common misroutes between similar document types
- **Use plain language** — avoid abbreviations and jargon the LLM won't recognise

If no `description` is provided, DocuFlow falls back to the workflow YAML's
`description:` field, or to a list of the schema's field names (e.g.
`"documents with fields: supplier_name, total"`). Field-name fallbacks work for
distinct schemas but fail when two schemas share similar fields — write an explicit
description in that case.

No-code version — a routes file:

```yaml
# routes.yaml
model: gemini/gemini-2.5-flash
workflows:
  - name: invoice
    description: supplier invoices with totals and line items
    workflow: workflows/invoices.yaml
  - name: claim
    description: motor insurance claim forms
    workflow: workflows/claims.yaml
```

```bash
docuflow route routes.yaml ./inbox --output results.csv
```

Honest costs and limits: classification adds one cheap LLM call per document
(~500 tokens). Misroutes can happen — the mitigation is built in: a misrouted
document extracted against the wrong schema produces nulls and unmatched evidence,
its quality score tanks, and review rules flag it. The router assumes one file = one
logical document; it does not split multi-document packets.

---

## 15. Document Comparison

Compare extracted fields across multiple documents.

```python
from docuflow import DocumentPipeline, compare_documents

pipeline = DocumentPipeline(parser="tesseract", model="openai/gpt-4o")

comparison = compare_documents(
    files=["contract_v1.pdf", "contract_v2.pdf", "contract_v3.pdf"],
    schema=Contract,
    pipeline=pipeline,
)

for field_name, cells in comparison.fields.items():
    diff = comparison.differences[field_name]
    status = "SAME" if diff.all_agree else "DIFFERENT"
    print(f"\n{field_name}: {status}")
    print(f"  Summary: {diff.summary}")
    for cell in cells:
        print(f"  {cell.file_name}: {cell.value} (conf: {cell.confidence:.2f})")
        for ev in cell.evidence:
            print(f"    Page {ev.page_number}, bbox: {ev.bbox}")
```

Each cell carries the full evidence (page, bbox, text) for highlighting where the value was found in each document.

---

## 16. Document Search & Highlighting

Search for text across a parsed document and get word-precise highlight rectangles.

```python
from docuflow.search import search_document

result = search_document(document, "Acme Corp")
print(f"Found {result.total_hits} matches")

for hit in result.hits:
    print(f"  Page {hit.page_number}: '{hit.text}'")
    print(f"    BBox: {hit.bbox}")        # union rect (single-page matches)
    print(f"    Rects: {hit.rects}")      # one rect per (page, line) segment
    print(f"    Context: ...{hit.context}...")
```

Parameters:
- `query` — text to search for
- `case_sensitive` — default `False`
- `context_chars` — characters of surrounding context to include (default: 50)
- `fuzzy` — set `True` to match OCR-garbled text approximately (returns the best
  match with its `match_ratio`)

Matching is normalization-aware (case, currency symbols, whitespace) and spans can
cross **word, line and page boundaries** — a phrase that wraps across lines (or runs
over a page break) returns one rect per line segment, the way a PDF viewer draws a
multi-line selection.

### The Text Locator

`search_document` is built on `locate_text`, which you can use directly for
highlight-oriented work:

```python
from docuflow.documents.locate import locate_text

spans = locate_text(document, "total amount due", find_all=True)
span = spans[0]
span.rects          # [PageRect] — one per (page, line) segment
span.bbox           # union bbox; None when the span crosses pages
span.confidence     # min OCR word confidence of the span (None without OCR)
span.match_ratio    # 1.0 exact; <1.0 fuzzy
span.block_ids      # the blocks the span touches
```

Field evidence uses the same machinery: `field.evidence[0].bbox` covers exactly the
matched words (not the whole line), and `field.evidence[0].rects` carries the per-line
rects for multi-line quotes.

### Overlaying Highlights on Rendered Pages

Bboxes are in the page's canonical coordinate space (see
[Coordinate Convention](#coordinate-convention)). To draw on a page rendered at any DPI:

```python
rel = hit.bbox.to_relative(page.width, page.height)   # 0-1 coords
x0_px = rel.x0 * image.width
y0_px = rel.y0 * image.height
```

---

## 17. Screenshots

Render document pages as PNG images for review UIs or visual inspection.

```python
from docuflow.screenshots import screenshot_pages_sync

# All pages
shots = screenshot_pages_sync("document.pdf", output_dir="./pages")

# Specific pages
shots = screenshot_pages_sync("document.pdf", output_dir="./pages", pages=[0, 2, 5])

# Custom DPI
shots = screenshot_pages_sync("document.pdf", output_dir="./pages", dpi=300)

for shot in shots:
    print(f"Page {shot.page_number}: {shot.width}x{shot.height} -> {shot.file_path}")
```

Bounding boxes live in the page's canonical point space, not screenshot pixels — use `bbox.to_relative(page.width, page.height)` and multiply by the screenshot's pixel dimensions to overlay highlights at any DPI.

---

## 18. Quality Report

`quality_report()` is a stateless function that assesses how well the model did on a single extraction (or a batch). No baseline needed — it reads the signals already in your `ExtractionResult`.

```python
from docuflow import quality_report

report = quality_report(result)
```

### Metrics

| Metric | What it measures |
|---|---|
| `score` | Weighted overall quality (0–1). Formula: 15% completeness + 25% evidence coverage + 25% grounding rate + 20% confidence + 15% auto-accept rate |
| `completeness_rate` | Fraction of fields with a non-None value (detects fields the model failed to extract) |
| `grounding_rate` | Fraction of present fields whose extracted value was found verbatim in the source text |
| `evidence_coverage` | Fraction of present fields that have at least one evidence object (page, bbox, text) |
| `mean_confidence` | Average confidence across present fields |
| `auto_accept_rate` | Fraction of present fields that pass the trust threshold (no review needed) |
| `correction_rate` | Fraction of present fields that were human-corrected via `correct_field()` |
| `ok` | `True` if `score >= threshold` (default threshold: 0.7) |

### Warnings

`report.warnings` is a list of human-readable strings explaining every issue:

```python
report.warnings
# ["Field 'total': not auto-accepted (agent disagreement)",
#  "Field 'date': value not found in source text",
#  "Field 'total': human-corrected"]
```

### Per-field drill-down

```python
fq = report.field_details["total"]
fq.found_in_source  # True
fq.has_evidence     # True
fq.trust_gate       # False
fq.corrected        # True
fq.missing          # False (True if value is None)
fq.warning          # "agent disagreement"
```

### Batch mode

Pass a list of results. Metrics are averaged, warnings are prefixed with the result index, and `worst_fields` shows the fields with lowest average quality across the batch.

```python
report = quality_report([result1, result2, result3])
report.n_results      # 3
report.score          # average score across all results
report.worst_fields   # ["total", "date"] — weakest fields
report.field_count    # total fields across all results
```

### Custom threshold

```python
report = quality_report(result, threshold=0.9)
report.ok  # True only if score >= 0.9
```

### Quality Snapshot and Log

Record quality over time with `QualityLog` — an append-only JSONL file of timestamped snapshots. Each snapshot captures the report's metrics plus freeform tags for slicing (by schema, model, data source, etc.).

```python
from docuflow.quality import QualityLog

log = QualityLog("./quality.jsonl")

# After each extraction
report = quality_report(result)
await log.record(report, tags={"schema": "Invoice", "model": "gpt-4o"})

# Sync variant
log.record_sync(report, tags={"schema": "Invoice", "model": "gpt-4o"})

# Read back — filter by tags, limit to last N
history = await log.history(last_n=50, tags={"schema": "Invoice"})
# or sync
history = log.history_sync(last_n=50, tags={"schema": "Invoice"})
```

Each snapshot contains: `snapshot_id`, `timestamp`, `tags`, `score`, `completeness_rate`, `grounding_rate`, `evidence_coverage`, `mean_confidence`, `auto_accept_rate`, `correction_rate`, `field_count`, `ok`.

You can also build a snapshot manually:

```python
from docuflow.quality import QualitySnapshot

snap = QualitySnapshot.from_report(report, tags={"schema": "Invoice"})
snap.snapshot_id   # unique UUID
snap.timestamp     # when it was created
snap.score         # 0.85
snap.tags          # {"schema": "Invoice"}
```

---

## 18b. Workflow Config

Define your entire extraction workflow in a single YAML file — schema, parser, model,
validation, review rules — and run it with one line. No Python imports to learn, no
classes to wire together.

This is more than convenience: the YAML file is a **portable, versionable artifact**.
Check it into git, review changes to it like code, hand it to a colleague who doesn't
write Python, run it from the CLI, serve it as an HTTP API, or generate a complete
Docker deployment from it (see [Serve & Dockerize](#18c-serve--dockerize-deployment)).
The same file works in all of these contexts unchanged.

### YAML format

```yaml
name: invoice-extraction
version: "1.0"
description: Standard invoice processing workflow

schema:
  supplier_name: {type: str, required: true, description: "Name of the supplier"}
  invoice_number: {type: str, description: "Invoice reference number"}
  total: {type: float, required: true, description: "Total amount including tax"}
  currency: {type: str, default: "EUR", description: "Currency code"}

parser: smart
model: openai/gpt-4o
extraction_mode: multi
n_instances: 3

validation:
  - required_fields: [supplier_name, total]
  - evidence_required: [total]

review:
  - overall_confidence_below: 0.7
  - field_missing: [total, invoice_number]

quality_threshold: 0.8
context: "You are processing motor insurance claim invoices."
```

### Running a workflow

```python
from docuflow import run_workflow

result = run_workflow("invoice.yaml", "invoice.pdf")
result.data       # {"supplier_name": "Acme", "total": 1234.56, ...}
result.confidence # 0.88
```

Or from the CLI:

```bash
docuflow run invoice.yaml invoice.pdf --output result.json
```

### Configuration reference

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | str | `"workflow"` | Workflow name |
| `version` | str | `"1.0"` | Version string |
| `schema` | dict | required | Field definitions (same format as YAML templates) |
| `parser` | str | `"auto"` | `"auto"` \| `"pdfplumber"` \| `"tesseract"` \| `"docling"` \| `"smart"` \| `"azure-di"` \| `"textract"` \| `"google-docai"` |
| `model` | str | `"openai/gpt-4o"` | Any litellm model string |
| `extraction_type` | str | `"text"` | `"text"` \| `"vision"` \| `"hybrid"` \| `"auto"` |
| `extraction_mode` | str | `"single"` | `"single"` \| `"multi"` |
| `n_instances` | int | `5` | Parallel instances for multi mode |
| `escalation` | dict | null | Auto-mode thresholds: `min_ocr_score`, `max_low_confidence_ratio`, `min_chars_per_page`, `escalate_to` |
| `verification` | dict | null | Zoom-and-verify: `trigger_consensus_below`, `trigger_ocr_below`, `max_fields`, `dpi`, `apply_corrections` |
| `schema_shards` | int | null | Split wide schemas into K parallel extractions (text only) |
| `context` | str | null | Domain context for the LLM |
| `validation` | list | `[]` | Validation rules (see below) |
| `review` | list | `[]` | Review rules (see below) |
| `quality_threshold` | float | `0.7` | Score threshold for `ok` flag |

### Validation rules (YAML)

```yaml
validation:
  - required_fields: [field1, field2]
  - evidence_required: [field1]
  - type_validation: true
```

### Review rules (YAML)

```yaml
review:
  - overall_confidence_below: 0.7
  - any_field_confidence_below: 0.5
  - field_confidence_below: {total: 0.9, date: 0.8}
  - has_validation_errors: true
  - field_missing: [total, invoice_number]
  - no_evidence: [total]          # specific fields
  - no_evidence: true             # all fields
  - llm_reviewer:
      name: auditor
      prompt: "Check if totals are mathematically consistent."
      model: openai/gpt-4o        # optional, defaults to workflow model
```

### Exporting a pipeline to YAML

If you already have a Python pipeline, export it:

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="smart", model="openai/gpt-4o", extraction_mode="multi",
    validators=[RequiredFields(["total"])],
)

# Export as dict
config = pipeline.export(Invoice, name="invoice", version="1.0")

# Export as YAML string
yaml_str = pipeline.export_yaml(Invoice, name="invoice")

# Save to file
with open("invoice.yaml", "w") as f:
    f.write(yaml_str)
```

### Loading programmatically

```python
from docuflow.workflow_config import load_workflow_config

cfg = load_workflow_config("invoice.yaml")  # or a dict
pipeline = cfg.build_pipeline()
schema = cfg.build_schema()
```

---

## 18c. Serve & Dockerize (Deployment)

Document extraction is rarely a whole application — usually it's one step inside a larger
system written in several languages. DocuFlow ships with a deployment story for exactly
that: **any workflow YAML can serve itself as an HTTP microservice, and can generate its
own Docker deployment.** No web code, no Dockerfile authoring.

```bash
pip install docuflow[serve]   # adds FastAPI, uvicorn, python-multipart
```

### Serving a workflow as an HTTP API

```bash
docuflow serve claims.yaml --port 8000
```

or programmatically:

```python
from docuflow.serve import create_app, run_server
from docuflow.workflow_config import load_workflow_config

config = load_workflow_config("claims.yaml")
app = create_app(config)      # a FastAPI app — mount it, test it, extend it
run_server("claims.yaml", port=8000)
```

Three endpoints:

| Endpoint | What it does |
|----------|-------------|
| `GET /health` | Workflow name, version, model, parser |
| `GET /schema` | The field definitions from the YAML |
| `POST /extract` | Upload a file → structured data + confidence scores + quality score + token usage |

Call it from anything — curl, JavaScript, Java, Go:

```bash
curl -F "file=@claim_form.pdf" http://localhost:8000/extract
```

The response is the full `ExtractionResult` JSON (data, fields, evidence, OCR and
consensus scores, usage) plus `quality_score` and `quality_ok`.

### Self-containerization

DocuFlow generates a complete, ready-to-build Docker deployment from a workflow file:

```bash
docuflow dockerize claims.yaml --output ./deploy
cd deploy && docker compose up --build
```

or:

```python
from docuflow.dockerize import generate_deployment

generate_deployment("claims.yaml", "./deploy")                     # stateless service
generate_deployment("claims.yaml", "./deploy", with_storage=True)  # adds a /data volume
```

The generated directory contains the Dockerfile, docker-compose.yml, the workflow YAML
and a pinned requirements file — everything needed to build and run the service. With
`--with-storage`, extractions persist to a mounted volume so results survive restarts.

The deployment flow end to end:

```
write claims.yaml  →  docuflow dockerize claims.yaml -o deploy  →  docker compose up
       ↑                                                              ↓
  (or export from an existing pipeline:                    POST /extract from any
   pipeline.export_yaml(schema))                           language in your stack
```

API keys are passed as environment variables at runtime (e.g. `OPENAI_API_KEY`) — they
are never baked into the image.

---

## 18d. PDF Form Filling

DocuFlow can also write trusted structured data into PDF forms. This is separate from
extraction: filling returns a dedicated `FillingResult`, not an `ExtractionResult`.

Install the writer dependencies:

```bash
pip install docuflow[forms]
```

### Fill an AcroForm PDF

Use this when the PDF has real form fields.

```python
from pydantic import BaseModel, Field
from docuflow import fill_pdf_form


class ClaimForm(BaseModel):
    claimant_name: str = Field(alias="claimant.name")
    policy_number: str
    accepted_terms: bool = False


data = ClaimForm(
    **{
        "claimant.name": "Mario Rossi",
        "policy_number": "POL-123456",
        "accepted_terms": True,
    }
)

result = fill_pdf_form(
    "blank-claim-form.pdf",
    data=data,
    output_path="filled-claim-form.pdf",
    strategy="auto",        # "auto" | "acroform" | "overlay"
)

result.success
result.output_path
result.strategy             # "acroform"
result.fields["claimant_name"].target_name
result.unmapped_model_fields
result.warnings
```

`strategy="auto"` inspects existing PDF form fields first. Matching uses Pydantic aliases,
field names, normalized names, or an explicit `field_map`.

### Static PDF Overlay

For PDFs with visual blanks but no real form fields, use `strategy="overlay"`. The default
path uses explicit placements. Coordinates use DocuFlow's normal page geometry: top-left
origin, usually PDF points.

```python
result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    field_map={
        "claimant_name": {
            "page_number": 0,
            "bbox": {"x0": 72, "y0": 120, "x1": 260, "y1": 140},
            "font_size": 10,
        }
    },
)
```

Automatic blank-space detection exists but is **off by default**. Enable it explicitly
when you want DocuFlow to infer labeled blank lines from PDF geometry:

```python
result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    detect_blank_spaces=True,  # opt-in, not active by default
)

result.fields["claimant_name"].method  # "auto_detected_blank"
result.warnings                        # includes detection summary
```

This detector is heuristic. It handles labeled blank lines, simple boxes, and underscore
blanks such as `Name: __________`. For high-stakes forms, explicit `field_map` placements
remain the most reliable option.

For harder static forms, use LLM-assisted detection:

```python
result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi", "address": "Via Roma 1"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    detect_blank_spaces=True,
    blank_detection_mode="llm",    # "heuristic" | "llm" | "hybrid"
    model="gemini/gemini-2.5-flash",
)

result.fields["claimant_name"].method  # "llm_detected_blank"
result.fields["claimant_name"].placement.confidence
result.fields["claimant_name"].placement.reason
```

The LLM is only a placement planner. It sees page images plus field names, aliases, and
descriptions; it does not receive the values to write. The LLM returns page-relative
coordinates (`0.0`–`1.0`, top-left origin), and DocuFlow converts them into the same
`BoundingBox` coordinate system used by extraction evidence, search hits, OCR spans, and
highlights before writing the PDF.

Use `blank_detection_mode="hybrid"` to run heuristic detection first and ask the LLM only
for fields the heuristic detector did not map.

### Review & Approval before saving (opt-in)

Because filling writes data *into* a file, any human review has to happen **before** the PDF
is saved. Pass `review=True` to **prepare** a fill without writing it: the plan is built and
review heuristics run, but `output_path` is not touched until you approve and commit. This is
off by default — `review=False` writes the PDF immediately, exactly as before.

```python
from docuflow import fill_pdf_form, preview_fill, commit_fill

# 1. Prepare — nothing is written yet
result = fill_pdf_form("claim-form.pdf", data, output_path="filled.pdf", review=True)
result.review_status        # "pending"
result.needs_review         # True when a heuristic flags the fill
result.review_reasons       # why it was flagged (low confidence, auto-detected blank, ...)
result.committed            # False

# 2. Show it — render each affected page with planned values overlaid (UI backend)
images = preview_fill(result, output_dir="./preview")   # -> list of PNG paths

# 3. Correct values and/or placements; originals are preserved and every edit is logged
result.edit_field("claimant_name", value="Maria Bianchi", corrected_by="alice", reason="typo")
result.edit_field("claimant_name", bbox={"x0": 100, "y0": 200, "x1": 300, "y1": 220})
result.corrections          # [FillCorrection(...)] full audit trail

# 4. Decide, then commit
result.approve(approved_by="alice")     # or result.reject(rejected_by="alice", reason="...")
commit_fill(result)                     # writes filled.pdf (requires approval, or force=True)
result.committed            # True
```

`edit_field()` is unified: pass `value=` to change what is written, and/or
`bbox` / `page_number` / `font_size` / `align` to change where/how (overlay). `commit_fill`
refuses a rejected result and refuses a pending one unless `force=True`; a result commits
only once. `preview_fill` highlights edited/warned fields in amber and clean ones in green;
no PDF is written. The `LocalDocumentStore` persists fills (`get_pending_fills()`,
`load_filling_result()`), the `FillForm` step takes `review=True`, and MCP exposes
`get_pending_fills` / `edit_fill_field` / `approve_fill` / `reject_fill`. Async variants:
`fill_pdf_form_async`, `preview_fill_async`, `commit_fill_async`.

### `FillingResult`

Important fields:

- `success` — whether any fields were written without errors
- `input_path`, `output_path` — source and generated PDF
- `schema_name` — Pydantic model class name, or `"Mapping"`
- `strategy` — `"acroform"` or `"overlay"`
- `data` — values supplied by the user
- `fields` — per-field `FilledField` objects with `value`, `formatted_value`, `target_name`, `page_number`, `bbox`, `method`, and warnings
- `pdf_fields` — discovered AcroForm fields
- `unmapped_model_fields`, `unmapped_pdf_fields`
- `warnings`, `errors`, `trace_id`
- `committed` — whether the PDF has actually been written (relevant with `review=True`)
- `needs_review`, `review_status`, `reviewed_by`, `reviewed_at`, `rejection_reason`, `review_reasons`
- `corrections` — `FillCorrection` audit log of reviewer edits (value and/or placement)

Manual pipelines can use `FillForm`:

```python
from docuflow.workflow import Pipeline, Ingest, FillForm

pipeline = Pipeline([
    Ingest(path="blank-form.pdf"),
    FillForm(data=data, output_path="filled-form.pdf"),
])

pipeline_result = pipeline.run_sync()
filling_result = pipeline_result.state.filling_result
```

For the full parameter reference, see [`docs/11-pdf-form-filling.md`](docs/11-pdf-form-filling.md).

---

## 18e. DOCX Form Filling

`fill_docx_form` fills Word documents using content controls (Word SDT form fields).
The same `FillingResult`, review/approval workflow, `edit_field`, and `commit_fill` apply.

```python
from docuflow import fill_docx_form, commit_fill
```

### Auto strategy

`"auto"` inspects the file and uses `"content_controls"` when SDT content controls are found.

```python
result = fill_docx_form(
    "claim-form.docx",
    data={"claimant_name": "Mario Rossi", "policy_number": "POL-42"},
    output_path="claim-form-filled.docx",
)
# result.strategy == "content_controls"  (if the docx has SDT fields)
```

### Discover what fields are available

```python
from docuflow.filling import inspect_content_controls

controls = inspect_content_controls("form.docx")     # list[FormField]
```

### Review and approval

Identical to the PDF path — `review=True` defers the write:

```python
result = fill_docx_form("form.docx", data, output_path="out.docx", review=True)
result.edit_field("policy_number", value="POL-CORRECTED", corrected_by="reviewer")
result.approve(approved_by="reviewer")
commit_fill(result)   # writes the DOCX now
```

### FillForm workflow step

`FillForm` dispatches automatically: `.docx` / `.doc` files → `fill_docx_form_async`;
all other files → `fill_pdf_form_async`. No change to the step API.

For the full reference, see [`docs/11-pdf-form-filling.md`](docs/11-pdf-form-filling.md).

---

## 18f. Document Splitting

`split_document` assigns each page of a PDF to one or more named sections using an LLM.
Sections are defined via a Pydantic model — field names become section identifiers and
`Field(description=...)` tells the LLM what belongs there.

```python
from pydantic import BaseModel, Field
from docuflow import split_document

class ContractSections(BaseModel):
    contract_body:  str = Field(description="Main contract terms and conditions")
    exhibits:       str = Field(description="Attached exhibits and appendices")
    signature_page: str = Field(description="Pages containing signature blocks")

result = split_document("contract.pdf", ContractSections)

print(result.page_map)
# {"contract_body": [0, 1, 2], "exhibits": [3, 4], "signature_page": [5]}
```

Alternatively, pass a list of `DocumentSection` objects:

```python
from docuflow.splitting import DocumentSection

result = split_document("contract.pdf", [
    DocumentSection(name="contract_body", description="Main contract terms"),
    DocumentSection(name="exhibits",      description="Attached exhibits"),
])
```

### Deep mode

`deep=True` adds per-section confidence (`"high"` / `"medium"` / `"low"`) and an evidence
statement:

```python
result = split_document("contract.pdf", ContractSections, deep=True)

for name, section in result.sections.items():
    print(f"{name}: pages {section.pages} ({section.confidence})")
    print(f"  {section.evidence}")
```

### Options

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | `"gemini/gemini-2.5-flash"` | Any LiteLLM model string. |
| `deep` | `False` | Also return confidence + evidence per section. |
| `allow_overlap` | `True` | A page may appear in multiple sections. |
| `split_rules` | `""` | Custom instruction overriding the default prompt logic. |
| `pages` | `None` | `list[int]` of 0-based page indices to process. `None` = all pages. |

### SplitResult

```python
result.success              # bool
result.page_map             # dict[str, list[int]] — sorted page indices
result.sections["body"].confidence   # "high" | "medium" | "low"
result.sections["body"].evidence     # str
result.usage                # token counts and cost
result.warnings             # out-of-range pages, etc.
```

For the full reference, see [`docs/12-document-splitting.md`](docs/12-document-splitting.md).

---

## 19. Storage

Storage persists documents, extraction results, and traces to disk.

### Local Storage

```python
pipeline = DocumentPipeline(storage="local")
# Saves to ./.docuflow_store/{document_id}/
```

Files saved per document:
- `original.pdf` — copy of the source file
- `document.json` — parsed Document (pages, blocks, text, metadata)
- `extraction.json` — ExtractionResult (fields, values, evidence, corrections, review status)
- `filling.json` — FillingResult for PDF form filling workflows
- `trace.json` — processing trace (events, timing)

### On Failure

When the pipeline fails with storage configured, partial state is automatically saved. This means you can inspect what happened:

```python
# After a failure, check .docuflow_store/{document_id}/
# document.json — exists if ingestion/parsing succeeded
# trace.json — exists with events up to the failure point
```

### Loading Results

```python
from docuflow.storage.local import LocalDocumentStore

store = LocalDocumentStore("./.docuflow_store")
result = await store.load_result("document-uuid")
document = await store.load_document("document-uuid")
```

### Custom Storage

Implement the `Storage` protocol:

```python
from docuflow.storage.base import Storage

class MyStorage:
    async def save_document(self, document: Document) -> str: ...
    async def save_result(self, result: ExtractionResult) -> str: ...
    async def save_filling_result(self, result: FillingResult) -> str: ...
    async def save_trace(self, trace: Trace) -> str: ...
    async def load_result(self, document_id: str) -> ExtractionResult | None: ...

pipeline = DocumentPipeline(storage=MyStorage())
```

---

## 20. Observability & Traces

Every pipeline step records trace events with timing information.

```python
# From DocumentPipeline (via WorkflowError on failure)
try:
    result = pipeline.run_sync("file.pdf", schema=Invoice)
except WorkflowError as e:
    for event in e.result.trace.events:
        print(f"{event.event_type}: {event.step_name} ({event.duration_ms:.0f}ms)")
        print(f"  Metadata: {event.metadata}")

# From manual Pipeline
pipeline_result = Pipeline([...]).run_sync()
for event in pipeline_result.trace.events:
    print(f"{event.event_type}: {event.step_name} ({event.duration_ms:.0f}ms)")
```

Event types include: `ingest`, `parse`, `anonymize`, `llm_call`, `vision_render`, `vision_ocr_enrichment`, `vision_llm_call`, `multi_extract_candidates`, `multi_extract_decider`, `hybrid_render`, `hybrid_candidates`, `hybrid_decider`, `fill_plan`, `fill_form`, `validate`, `review`, `store`, `error`.

---

## 21. Error Handling

All DocuFlow errors inherit from `DocuflowError`:

```python
from docuflow.errors import (
    DocuflowError,            # base class
    UnsupportedFileTypeError,# unknown file extension
    ParsingError,            # PDF parsing or file access failure
    OCRError,                # Tesseract OCR failure
    SchemaExtractionError,   # LLM call or JSON parse failure
    ValidationError,         # field validation failure
    EvidenceNotFoundError,   # evidence matching failure
    StorageError,            # storage read/write failure
    WorkflowError,           # pipeline step failure (carries result)
    PrivacyError,            # privacy operation failure
    AnonymizationError,      # anonymization failure
)
```

### Handling Pipeline Failures

```python
from docuflow.errors import WorkflowError

try:
    result = pipeline.run_sync("file.pdf", schema=Invoice)
except WorkflowError as e:
    print(f"Error: {e}")
    print(f"Errors: {e.result.errors}")
    print(f"Failed step: {e.result.state.current_step}")
    print(f"Document: {e.result.state.document}")
    print(f"Trace: {e.result.trace.events}")
```

The `WorkflowError.result` contains the full `PipelineResult` with partial state, so you can inspect exactly what succeeded and what failed.

---

## 22. CLI Reference

### Run a YAML Workflow

```bash
docuflow run claims.yaml claim_form.pdf --output result.json
```

### Serve a Workflow as an HTTP API

```bash
docuflow serve claims.yaml --port 8000
```

### Generate a Docker Deployment

```bash
docuflow dockerize claims.yaml --output ./deploy
docuflow dockerize claims.yaml --output ./deploy --with-storage
```

### Extract a Single Document

```bash
docuflow extract invoice.pdf --schema invoice --model openai/gpt-4o --output result.json
```

Options:
- `--schema, -s` (required) — schema name or Python dotted path
- `--model, -m` — LLM model (default: `openai/gpt-4o`)
- `--output, -o` — output file (default: stdout)
- `--store` — storage backend (e.g., `local`)

### Route a Mixed Folder

```bash
docuflow route routes.yaml ./inbox --output results.csv
```

Classifies each document and runs the matching workflow from the routes file.

### Extract a Folder

```bash
docuflow extract-folder ./invoices --schema invoice --output results.csv --parser smart --concurrency 10
```

Options:
- `--schema, -s` (required) — schema name or Python dotted path
- `--model, -m` — LLM model (default: `openai/gpt-4o`)
- `--parser, -p` — parser (default: `auto`). Options: `auto`, `pdfplumber`, `tesseract`, `docling`, `smart`, `azure-di`, `textract`, `google-docai`
- `--output, -o` — output CSV file
- `--pattern` — file glob pattern (default: `**/*.pdf`)
- `--concurrency, -c` — max parallel extractions (default: 5)

### Take Screenshots

```bash
docuflow screenshot document.pdf -o ./pages --dpi 300
docuflow screenshot document.pdf -o ./pages --pages 0,2,5
```

Options:
- `--output, -o` (required) — output directory
- `--dpi` — rendering DPI (default: 200)
- `--pages` — comma-separated page numbers (default: all)

### Manage Templates

```bash
docuflow templates list
docuflow templates show invoice
docuflow templates init invoice --dir ./my_templates
```

---

## 23. API Reference

### Top-Level Imports

```python
# Core
from docuflow import extract, DocumentPipeline, Pipeline, PrivacyPolicy
from docuflow import process_batch, compare_documents, fill_pdf_form, fill_docx_form
from docuflow import split_document, split_document_async

# Parsers
from docuflow.parsing.pdfplumber_parser import PdfplumberParser
from docuflow.parsing.tesseract_parser import TesseractParser
from docuflow.parsing.docling_parser import DoclingParser
from docuflow.parsing.smart_parser import SmartParser

# Templates
from docuflow.templates import load_template, list_templates

# Validation
from docuflow.validation import RequiredFields, EvidenceRequired, TypeValidation, CustomRule

# Review
from docuflow.review import (
    OverallConfidenceBelow, FieldConfidenceBelow, AnyFieldConfidenceBelow,
    HasValidationErrors, FieldMissing, NoEvidence, LLMReviewer,
)

# Privacy
from docuflow.privacy import PrivacyPolicy, Anonymizer, PresidioProvider
from docuflow.privacy.mapping_store import LocalMappingStore
from docuflow.privacy.image_redaction import ImageRedactor
from docuflow.privacy.scrubber import TraceScrubber

# Storage
from docuflow.storage.local import LocalDocumentStore

# LLM
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

# Pipeline Steps
from docuflow.workflow import (
    Pipeline, Ingest, Parse, Extract, ExtractVision, ExtractHybrid,
    Anonymize, FillForm, Validate, Review, Store,
)

# Utilities
from docuflow.search import search_document
from docuflow.screenshots import screenshot_pages_sync
from docuflow.quality import quality_report, QualityReport
from docuflow.batch import process_batch, BatchReport
from docuflow.comparison import compare_documents, ComparisonResult

# Models
from docuflow.documents.models import Document, Page, Block, BoundingBox, BlockType
from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import (
    ExtractionResult, ExtractedField, FieldCorrection,
    ReviewVerdict, FieldProvenance,
)
from docuflow.filling import (
    FillingResult, FilledField, FieldPlacement, FormField,
    fill_docx_form, fill_docx_form_async,
    inspect_content_controls,
)
from docuflow.splitting import split_document, split_document_async, DocumentSection, SplitResult
```
