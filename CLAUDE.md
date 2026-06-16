# DocuFlow — Agent Integration Guide

This file tells AI coding agents everything they need to know to integrate DocuFlow into a project.

For the full user-facing technical library documentation, read the Markdown files under `docs/`.
Those files are the source of truth for public APIs, selectable parameters, supported options,
and usage examples. Use this file as the agent integration quick reference.

## What DocuFlow Does

DocuFlow extracts structured data from documents (PDFs, scans, images) using LLMs. You define a Pydantic schema, point it at a document, and get back validated fields with evidence, confidence scores, and bounding boxes.

## Installation

```bash
pip install docuflow[all]          # Everything
pip install docuflow[pdf,llm]      # Lightweight: pdfplumber + LLM only
pip install docuflow[ocr,llm]      # Tesseract OCR + LLM
pip install docuflow[docling,llm]  # Docling (best parsing) + LLM
```

Requires Python >= 3.11.

## Core API — 3 Ways to Use

### 1. One-liner (simplest)

```python
from docuflow import extract

result = extract("invoice.pdf", schema=Invoice, model="openai/gpt-4o")
```

### 2. DocumentPipeline (configurable, reusable)

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="auto",              # "auto" | "pdfplumber" | "tesseract" | "docling" | "smart"
    model="openai/gpt-4o",      # any litellm model string
    extraction_type="text",     # "text" | "vision" | "hybrid" | "auto"
    extraction_mode="single",   # "single" | "multi"
    storage="local",            # None | "local" | Storage instance
)
result = pipeline.run_sync("invoice.pdf", schema=Invoice)
```

### 3. Manual Pipeline (full control)

```python
from docuflow.workflow import Pipeline, Ingest, Parse, Extract, Validate, Review, Store

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
from docuflow.templates import load_template
Invoice = load_template("invoice")  # built-in: invoice, contract, receipt
```

## Parsers — Choosing the Right One

| Parser | Use when | Speed | Install |
|--------|----------|-------|---------|
| `"auto"` | Source-aware default: text/email skip parsing, images use OCR, PDFs use native/smart parsing, Office files use Docling | Varies | Depends on input type |
| `"pdfplumber"` | Digital/native PDFs | Fast (~100ms) | `docuflow[pdf]` |
| `"tesseract"` | Scanned documents | Slow (1-5s/page) | `docuflow[ocr]` |
| `"docling"` | Complex layouts, tables | Slow (4-5s/page) | `docuflow[docling]` |
| `"smart"` | Mixed docs (auto-detects per page) | Varies | `docuflow[pdf,ocr]` |
| `"azure-di"` | Cloud OCR, Azure Document Intelligence | API call | `docuflow[azure]` |
| `"textract"` | Cloud OCR, AWS Textract | API call/page | `docuflow[aws,pdf]` |
| `"google-docai"` | Cloud OCR, Google Document AI | API call | `docuflow[gcp]` |

### Cloud OCR configuration

```python
# Azure Document Intelligence — or env vars AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT / _KEY
pipeline = DocumentPipeline(parser={"type": "azure-di", "model": "prebuilt-read"})

# AWS Textract — credentials via standard boto3 chain; pages rendered locally, no S3 needed
pipeline = DocumentPipeline(parser={"type": "textract", "region": "eu-west-1"})

# Google Document AI — or env vars GOOGLE_DOCAI_PROJECT / _LOCATION / _PROCESSOR_ID
pipeline = DocumentPipeline(parser={"type": "google-docai", "project": "p", "processor_id": "x"})
```

All parsers produce the same standardized `Document`: pages of **line-level blocks**, where OCR-based parsers also fill per-word `words` (text, bbox, confidence) and a line `confidence`. Native parsers (pdfplumber) leave confidence empty — downstream code treats that as "no OCR ran". Docling is hybrid: when its internal OCR fires (scanned pages), the OCR cell confidences are attached to the layout blocks; native Docling parses report no OCR confidence, by design.

Default `parser="auto"` keeps `Document` as the internal standard across input types:
text-like files (`txt`, `md`, `html`, `csv`, `json`, `xml`, `eml`) are normalized by
ingestion into a one-page parsed document, images are OCR'd for text extraction or
rendered directly for vision/hybrid, PDFs use native/smart parsing, and Office/spreadsheet
files route to Docling.

## Extraction Types

| Type | Pipeline | What happens |
|------|----------|-------------|
| `"text"` | Parse → Extract | Parser gives text, LLM reads text |
| `"vision"` | ExtractVision (no parser) | Pages rendered as images → vision LLM |
| `"hybrid"` | ExtractHybrid (no parser) | Vision + text agents parallel → vision decider |
| `"auto"` | Parse (smart) → ExtractAuto | Text extraction; escalates to vision when OCR quality is poor |

### Auto mode (vision escalation)

```python
pipeline = DocumentPipeline(
    extraction_type="auto",
    escalation={"min_ocr_score": 0.6, "max_low_confidence_ratio": 0.4, "escalate_to": "vision"},
)
result.escalated           # True if re-read by the vision LLM
result.escalation_reason   # e.g. "OCR confidence 0.42 below threshold 0.6"
```

OCR fails *confidently* — bad scans return plausible garbage, not errors. Auto mode
gates on the OCR confidence scores after parsing and re-reads the original file with
the vision (or hybrid) engine when quality is below threshold. Escalation is suppressed
when a PrivacyPolicy is configured (vision bypasses text anonymization).

## Zoom-and-Verify (per-field verification)

After extraction, fields with weak signals (low consensus, low/unmatched OCR span) can
be re-read individually: the field's page is rendered at high DPI, cropped to the
field's highlight rect (plus padding), and a vision LLM answers a focused question
about just that region. Costs pennies vs a full re-extraction.

```python
pipeline = DocumentPipeline(
    verification={                      # enables the VerifyFields step
        "trigger_consensus_below": 0.7, # verify when consensus ratio is below
        "trigger_ocr_below": 0.6,       # verify when OCR span score is below
        "include_unmatched": True,      # verify values OCR couldn't locate
        "max_fields": 5,                # cost cap per document
        "dpi": 300,                     # zoom render DPI
        "apply_corrections": True,      # apply schema-valid corrections
    },
)

field.verification                 # FieldVerification | None
field.verification.agrees          # re-read confirmed the value (confidence -> >= 0.9)
field.verification.changed         # correction applied (original in original_value)
field.verification.verified_value  # what the zoomed re-read returned
field.verification.reason          # why this field was verified
```

Corrections only apply when the new value passes schema validation; changed fields
keep confidence <= 0.6 so review rules still catch them. Verification token usage is
merged into `result.usage`. Works in YAML via a `verification:` block. Requires a
vision-capable model.

**Vision and hybrid require `parser=None`:**

```python
pipeline = DocumentPipeline(parser=None, extraction_type="vision", model="openai/gpt-4o")
```

## Schema Sharding & Prompt Caching

```python
# Wide schemas: K parallel partial-schema extractions, merged (text only)
pipeline = DocumentPipeline(schema_shards=3)

# Anthropic prompt caching for repeated workflow runs (OpenAI caches automatically)
pipeline = DocumentPipeline(model="anthropic/claude-sonnet-4-6",
                            llm_kwargs={"prompt_caching": True})
```

## Extraction Modes

| Mode | LLM calls | Description |
|------|-----------|-------------|
| `"single"` | 1 | One LLM call |
| `"multi"` | N+1 (N when unanimous) | N parallel calls at varied temperatures → decider picks best; the decider is skipped when all candidates agree on every field |

```python
pipeline = DocumentPipeline(extraction_mode="multi", n_instances=3)
```

## Output — ExtractionResult

```python
result = pipeline.run_sync("invoice.pdf", schema=Invoice)

result.data                          # {"supplier_name": "Acme", "total": 1234.56}
result.fields["total"].value         # 1234.56
result.fields["total"].trust_gate    # True/False
result.fields["total"].evidence[0].text        # "1234.56"
result.fields["total"].evidence[0].page_number # 0
result.fields["total"].evidence[0].bbox        # BoundingBox(x0=72, y0=130, x1=200, y1=148)
result.confidence                    # 0.85 (overall)
result.usage                         # TokenUsage | None — aggregated LLM token usage
result.usage.prompt_tokens           # summed across ALL calls (instances, decider,
result.usage.completion_tokens       #   JSON-repair retries, LLM reviewers)
result.usage.total_tokens
result.usage.n_llm_calls             # how many LLM calls produced this result
result.usage.cost_usd                # litellm-priced cost (None if model unknown)
result.needs_review                  # True/False
result.review_reasons                # ["Field 'total' trust gate false"]
result.review_verdicts               # [ReviewVerdict(reviewer="auditor", verdict="Approved")]
result.model_dump_json()             # full JSON serialization
```

## Validation

```python
from docuflow.validation import RequiredFields, EvidenceRequired

pipeline = DocumentPipeline(
    validators=[
        RequiredFields(["supplier_name", "total"]),
        EvidenceRequired(["total"]),
    ],
)
```

## Review Rules

```python
from docuflow.review import (
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
from docuflow.review import LLMReviewer
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

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
p.model_name, p.parser_name, p.trust_gate, p.evidence_confidence
p.validation_status, p.review_status, p.reviewed_by
p.corrected, p.corrected_by, p.correction_reason
```

## Privacy / Anonymization

```python
from docuflow import DocumentPipeline, PrivacyPolicy
from docuflow.privacy import PresidioProvider

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
    context="You work in motor insurance claims processing. Policy numbers follow the pattern POL-XXXXXXX.",
)
```

## Batch Processing

```python
from docuflow import DocumentPipeline, process_batch

pipeline = DocumentPipeline(parser="smart", model="openai/gpt-4o")
report = process_batch(
    files=["inv1.pdf", "inv2.pdf", "inv3.pdf"],
    schema=Invoice,
    pipeline=pipeline,
)
report.total, report.succeeded, report.failed, report.needs_review
report.average_confidence
report.usage               # TokenUsage | None — tokens/cost summed over the whole batch
report.top_review_reasons
report.to_csv()            # CSV string
report.to_dataframe()      # pandas DataFrame
```

## Routing Mixed Document Streams

```python
from docuflow import WorkflowRouter

router = WorkflowRouter()  # classifier: gemini/gemini-2.5-flash (one cheap call/doc)
router.register("invoice", "workflows/invoices.yaml")
router.register("claim", pipeline=claims_pipeline, schema=ClaimForm,
                description="motor insurance claim forms")

report = router.route_sync(files, concurrency=5)
report.by_workflow      # {"invoice": [RoutedResult...], "claim": [...]}
report.unclassified     # never force-extracted with the wrong schema
report.usage            # includes classification token cost
```

CLI: `docuflow route routes.yaml ./inbox --output results.csv` (routes.yaml lists
name/description/workflow entries). Scans with no text layer classify from a
low-DPI page-1 image. One file = one document (no packet splitting).

## Document Comparison

```python
from docuflow import compare_documents

comparison = compare_documents(
    files=["v1.pdf", "v2.pdf", "v3.pdf"],
    schema=Contract,
    pipeline=pipeline,
)
for field, cells in comparison.fields.items():
    diff = comparison.differences[field]
    print(f"{field}: {'SAME' if diff.all_agree else 'DIFFERENT'} — {diff.summary}")
```

## Search & Text Location (Highlighting)

```python
from docuflow.search import search_document

result = search_document(document, "Acme Corp")          # exact (normalized)
result = search_document(document, "INV-001", fuzzy=True)  # tolerate OCR garble
for hit in result.hits:
    hit.bbox       # union rect (single-page matches)
    hit.rects      # [PageRect] — one rect per (page, line) segment
    hit.match_ratio  # 1.0 exact, <1.0 fuzzy
    hit.context
```

Lower-level: `locate_text()` finds any phrase at word-span precision —
matches cross word, line and **page** boundaries:

```python
from docuflow.documents.locate import locate_text

spans = locate_text(document, "carried forward to the next page", find_all=True)
span = spans[0]
span.rects        # one PageRect per (page, line) — render like a PDF viewer selection
span.bbox         # union bbox (None when the span crosses pages)
span.confidence   # min OCR word confidence of the span (None without OCR)
span.match_ratio  # 1.0 exact; fuzzy fallback for OCR-garbled text
```

### Coordinate convention

All bboxes in a document share one coordinate space per page: **top-left
origin, PDF points (72/inch)** — `Page.unit == "pt"`. OCR parsers convert
their rendered-pixel coords via DPI; Azure DI converts inches. Providers
with unknowable physical size (Google DocAI on pixels) keep `unit="px"`,
still consistent with `Page.width/height`. To overlay a highlight on a page
rendered at any DPI:

```python
rel = hit.bbox.to_relative(page.width, page.height)  # 0-1 coords
# pixel rect = rel * rendered_image_size — works for every parser
```

Evidence carries the same precision: `field.evidence[0].bbox` covers exactly
the matched words and `field.evidence[0].rects` handles multi-line spans.
`field.ocr.bbox` / `field.ocr.rects` give the highlight for the OCR-scored span.

## Screenshots

```python
from docuflow.screenshots import screenshot_pages_sync

shots = screenshot_pages_sync("doc.pdf", output_dir="./pages", dpi=200)
```

## PDF and DOCX Form Filling

PDF and DOCX write-back is separate from extraction and returns `FillingResult`, not `ExtractionResult`.

```bash
pip install docuflow[forms]
```

```python
from docuflow import fill_pdf_form

result = fill_pdf_form(
    "blank-form.pdf",
    data=form_data,              # Pydantic instance or mapping
    output_path="filled-form.pdf",
    strategy="auto",             # "auto" | "acroform" | "overlay"
    match_by="auto",             # "auto" | "name" | "alias" | "manual" | "label" | "llm"
    field_map=None,              # PDF field map or overlay placements
    detect_blank_spaces=False,   # opt-in static blank detection; off by default
    blank_detection_mode="heuristic",  # "heuristic" | "llm" | "hybrid"
    overflow="shrink",           # "shrink" | "wrap" | "error" | "page"
)

result.success
result.output_path
result.strategy                  # "acroform" | "overlay"
result.fields                    # dict[str, FilledField]
result.unmapped_model_fields
result.unmapped_pdf_fields
result.warnings
result.errors
```

`strategy="acroform"` writes existing PDF form fields. `strategy="overlay"` writes values at
explicit `field_map` placements using DocuFlow top-left page coordinates. Automatic static
blank-space detection exists only when `detect_blank_spaces=True`; it is heuristic and off
by default. Use `blank_detection_mode="llm"` for a vision LLM placement planner, or
`"hybrid"` to use heuristic placements first and LLM for missing fields. The LLM returns
relative 0-1 top-left boxes, which DocuFlow converts to standard `BoundingBox` page
coordinates before writing. Manual pipelines can use `FillForm`.

### Review & Approval (opt-in)

Filling writes data *into* a file, so review must happen before the PDF is saved. Pass
`review=True` to **prepare** a fill without writing it: the plan is built, review heuristics
run, but `output_path` is not written until you approve and commit. Review is off by default
(`review=False` writes immediately, as before).

```python
from docuflow import fill_pdf_form, preview_fill, commit_fill

# 1. Prepare (nothing is written yet)
result = fill_pdf_form("form.pdf", data, output_path="filled.pdf", review=True)
result.review_status      # "pending"
result.needs_review       # True if any review heuristic flagged the fill
result.review_reasons     # ["Field 'name' was located by automatic blank detection", ...]
result.committed          # False

# 2. Show it (backend for a UI): renders each affected page with planned values overlaid
images = preview_fill(result, output_dir="./preview")   # list of PNG paths

# 3. Correct values and/or placements before saving
result.edit_field("name", value="Maria Bianchi", corrected_by="alice", reason="typo")
result.edit_field("name", bbox={"x0": 100, "y0": 200, "x1": 300, "y1": 220}, page_number=0)
result.corrections        # [FillCorrection(...)] — full audit log, original values preserved

# 4. Approve (or reject) and commit
result.approve(approved_by="alice")          # or result.reject(rejected_by="alice", reason="...")
commit_fill(result)                          # writes filled.pdf (requires approval, or force=True)
result.committed          # True
```

`edit_field()` is unified: pass `value=` to change what is written, and/or `bbox` /
`page_number` / `font_size` / `align` to change where/how (overlay). Each edit preserves the
original and appends a `FillCorrection`. `commit_fill(result, force=True)` writes a still-pending
result without approval. A rejected result cannot be committed. Async variants:
`fill_pdf_form_async`, `preview_fill_async`, `commit_fill_async`.

`LocalDocumentStore` persists fills to `filling.json`; query pending ones with
`await store.get_pending_fills()` and reload with `await store.load_filling_result(doc_id)`.
The `FillForm` pipeline step takes `review=True` too. MCP exposes `get_pending_fills`,
`edit_fill_field`, `approve_fill`, and `reject_fill`.

### DOCX Form Filling

`fill_docx_form` fills `.docx` files by writing into native Word content controls,
reusing the same `FillingResult`, review/approval, `edit_field`, and `commit_fill`
surface as PDF filling.

```python
from docuflow import fill_docx_form
from docuflow.filling import DocxFillStrategy

result = fill_docx_form(
    "blank-form.docx",
    data=form_data,              # Pydantic instance or mapping
    output_path="filled-form.docx",
    strategy="auto",             # "auto" | "content_controls"
    review=False,
)
```

Write strategy:

| Strategy | When to use |
|----------|-------------|
| `"content_controls"` | Word has native form fields (`w:sdt` SDT elements — dropdowns, checkboxes, date pickers, plain-text controls). Auto-detected. |
| `"auto"` | Inspects for SDT elements and fills them via `content_controls`. |

```bash
pip install docuflow[forms]   # includes python-docx
```

Lower-level inspect helper:

```python
from docuflow.filling import inspect_content_controls

fields = inspect_content_controls("form.docx")  # list[FormField]
```

The review/approval workflow, `edit_field`, `preview_fill`, and `commit_fill` all work
identically for DOCX — the DOCX preview returns an empty list (not yet supported).

## Document Splitting

Assign document pages to named logical sections using an LLM:

```bash
pip install docuflow[pdf,llm]
```

```python
from pydantic import BaseModel, Field
from docuflow import split_document
from docuflow.splitting import DocumentSection, SplitResult

class ContractSections(BaseModel):
    contract_body: str = Field(description="Main contract terms and conditions")
    exhibits:      str = Field(description="Attached exhibits and appendices")
    signature_page: str = Field(description="Pages containing signature blocks")

result = split_document("contract.pdf", ContractSections)
result.page_map   # {"contract_body": [0, 1, 2], "exhibits": [3, 4], "signature_page": [5]}
result.success    # True
```

Or pass a list of `DocumentSection` objects for dynamic section names:

```python
result = split_document("contract.pdf", [
    DocumentSection(name="contract_body", description="Main contract terms"),
    DocumentSection(name="exhibits",      description="Attached exhibits"),
])
```

Key parameters: `model` (LiteLLM string, default `"gemini/gemini-2.5-flash"`), `deep=True`
for per-section `confidence` + `evidence`, `allow_overlap=False` to enforce one section per
page, `split_rules` for a freeform prompt override, `pages` for a page-index subset.

```python
result = split_document("contract.pdf", ContractSections, deep=True)
for name, section in result.sections.items():
    print(f"{name}: {section.pages} ({section.confidence}) — {section.evidence}")
```

MCP exposes `split_document` (sections as JSON string). Full reference: `docs/12-document-splitting.md`.

## Document Metadata Extraction

Extract PDF annotations and DOCX structural elements:

```python
from docuflow import extract_metadata
from docuflow.metadata import DocumentMetadataResult

result = extract_metadata("contract.pdf")   # or .docx
result.comments     # list[Comment]   — reviewer notes (author, date, text, bbox)
result.highlights   # list[Highlight] — subtype, color (hex), bbox
result.hyperlinks   # list[Hyperlink] — url, text, bbox
result.signatures   # list[Signature] — field_name, signed, signer (PDF only)
result.revisions    # list[Revision]  — insertion/deletion, author, date (DOCX only)
result.has_metadata
```

No extra install — uses pypdf (`[forms]`) for PDF, stdlib for DOCX. Full reference: `docs/13-document-metadata.md`.

## Quality Report

```python
from docuflow import quality_report

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
from docuflow.quality import QualityLog

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
from docuflow import run_workflow

result = run_workflow("invoice.yaml", "invoice.pdf")
```

```bash
docuflow run invoice.yaml invoice.pdf --output result.json
```

Export an existing pipeline:

```python
yaml_str = pipeline.export_yaml(Invoice, name="invoice")
```

## Storage

```python
pipeline = DocumentPipeline(storage="local")  # saves to .docuflow_store/
# Saves: original.pdf, document.json, extraction.json, filling.json, trace.json
# On failure: partial state auto-saved if storage is configured
```

## Error Handling

```python
from docuflow.errors import WorkflowError

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
pip install docuflow[serve]  # adds fastapi, uvicorn, python-multipart
```

### Local server

```python
from docuflow.serve import create_app, run_server
from docuflow.workflow_config import load_workflow_config

config = load_workflow_config("workflow.yaml")
app = create_app(config)  # FastAPI app with /health, /schema, /extract
run_server("workflow.yaml", port=8000)
```

### Docker deployment

```python
from docuflow.dockerize import generate_deployment

generate_deployment("workflow.yaml", "./deploy")              # stateless
generate_deployment("workflow.yaml", "./deploy", with_storage=True)  # with /data volume
```

### Endpoints

- `GET /health` — workflow name, version, model, parser
- `GET /schema` — field definitions
- `POST /extract` — upload file, returns structured data + quality_score + quality_ok

### CLI

```bash
docuflow serve workflow.yaml --port 8000
docuflow dockerize workflow.yaml --output ./deploy
docuflow dockerize workflow.yaml --output ./deploy --with-storage
```

## CLI

```bash
docuflow extract file.pdf --schema invoice --output result.json
docuflow extract-folder ./invoices --schema invoice --output results.csv --parser smart
docuflow run workflow.yaml invoice.pdf --output result.json
docuflow serve workflow.yaml --port 8000
docuflow dockerize workflow.yaml --output ./deploy --with-storage
docuflow screenshot file.pdf -o ./pages --dpi 200
docuflow templates list
docuflow templates show invoice
docuflow templates init invoice
```

## Key Imports

```python
# Top-level
from docuflow import extract, fill_pdf_form, fill_docx_form, DocumentPipeline, Pipeline, PrivacyPolicy
from docuflow import process_batch, compare_documents, split_document, extract_metadata

# Parsing
from docuflow.parsing.pdfplumber_parser import PdfplumberParser
from docuflow.parsing.tesseract_parser import TesseractParser
from docuflow.parsing.docling_parser import DoclingParser
from docuflow.parsing.smart_parser import SmartParser

# Templates
from docuflow.templates import load_template, list_templates

# Validation
from docuflow.validation import RequiredFields, EvidenceRequired, TypeValidation

# Review
from docuflow.review import (
    OverallConfidenceBelow, FieldConfidenceBelow, AnyFieldConfidenceBelow,
    HasValidationErrors, FieldMissing, NoEvidence, LLMReviewer,
)

# Privacy
from docuflow.privacy import PrivacyPolicy, Anonymizer, PresidioProvider

# Storage
from docuflow.storage.local import LocalDocumentStore

# LLM
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

# Pipeline steps (for manual Pipeline)
from docuflow.workflow import (
    Pipeline, Ingest, Parse, Extract, ExtractVision, ExtractHybrid,
    Anonymize, FillForm, Validate, Review, Store,
)

# Utilities
from docuflow.search import search_document
from docuflow.screenshots import screenshot_pages_sync
from docuflow.quality import quality_report, QualityReport, QualitySnapshot, QualityLog
from docuflow import fill_pdf_form, fill_docx_form, commit_fill, preview_fill
from docuflow.filling import (
    FillingResult, FilledField, FieldPlacement, FormField, FillCorrection,
    commit_fill, commit_fill_async, preview_fill, preview_fill_async, evaluate_fill_review,
    inspect_content_controls,
)
from docuflow.splitting import DocumentSection, SplitResult, SectionResult
from docuflow.workflow_config import load_workflow_config, run_workflow, WorkflowConfig
from docuflow.batch import process_batch, BatchReport
from docuflow.comparison import compare_documents, ComparisonResult
```

## Schema Discovery

Auto-generate a schema from a document — the LLM reads it and suggests fields:

```python
from docuflow import discover_schema

discovery = discover_schema("invoice.pdf")
print(discovery.document_type)     # "invoice"
print(discovery.fields)            # [DiscoveredField(name="supplier_name", type="str", ...)]

# Use immediately
Invoice = discovery.schema_class
result = extract("invoice.pdf", schema=Invoice)

# Or save as YAML template
with open("docuflow_templates/my_invoice.yaml", "w") as f:
    f.write(discovery.yaml_template)
```

## Structured Tables (Docling parser only)

When using `parser="docling"`, tables are extracted as first-class objects:

```python
from docuflow.documents.tables import Table, Cell

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

DocuFlow uses agreement + source verification, NOT LLM self-reported confidence:

```python
field.trust.agreement        # "4/5" (multi mode) or "" (single mode)
field.trust.agreement_ratio  # 0.8 (multi) or 0.0 (single — no consensus)
field.trust.found_in_source  # True/False
field.trust.trust_gate       # True = skip review, False = needs review
field.trust_gate             # same boolean gate on the field itself

# Fixed trust behavior. Use result.confidence_score / result.consensus_score for the final result.
pipeline = DocumentPipeline()
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
from docuflow.eval import EvalHarness

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

DocuFlow runs as an MCP server with 21 tools any AI agent can call:

```bash
pip install docuflow[mcp]
docuflow-mcp  # starts the server
```

Tools: `extract_document`, `extract_with_vision`, `discover_schema`, `compare_documents`, `process_batch`, `list_templates`, `show_template`, `search_in_document`, `get_pending_reviews`, `get_extraction_result`, `correct_field`, `approve_document`, `reject_document`, `screenshot_document`, `get_pending_fills`, `edit_fill_field`, `approve_fill`, `reject_fill`, `split_document`, `fill_docx_form`, `extract_document_metadata`.

## Project Structure

```
src/docuflow/
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
  mcp_server.py        # MCP server (21 tools for AI agents)
  constants.py         # DEFAULT_DPI
  errors.py            # All exception classes
  documents/           # Document, Page, Block, Evidence, Table, Cell
  extraction/          # ExtractionEngine, VisionExtractionEngine, HybridExtractionEngine
    llm/               # LLMAdapter protocol, LiteLLMAdapter
  filling/             # fill_pdf_form, fill_docx_form, FillingResult, AcroForm/overlay/DOCX writers
  splitting/           # split_document, SplitResult, DocumentSection, LLM-based page assignment
  parsing/             # Parser protocol, pdfplumber, Tesseract, Docling, Smart
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
