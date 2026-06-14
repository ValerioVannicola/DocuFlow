<p align="center">
  <img src="docs/assets/docuflow-logo.png" alt="DocuFlow logo" width="920">
</p>


#### DocuFlow turns unstructured documents into production-ready data. Unlike typical extraction tools that stop at raw JSON, DocuFlow adds evidence, consensus, verification, validation, and auditability so you can trust, review, and ship the result.

## Why DocuFlow?

Most document extraction tools focus on one part of the problem: parsing a PDF, running OCR, or calling an LLM. In real workflows, that is rarely enough. Teams also need schemas, evidence, trust signals, validation, privacy controls, review steps, corrections, storage, and an audit trail they can rely on.

DocuFlow is a workflow runtime for document extraction. It combines parsers, OCR, LLMs, validation rules, review logic, consensus, verification, and deployment options into one reproducible pipeline, so extracted data can move from messy documents into production systems with traceability and control.

## Installation

```bash
pip install docuflow[all]
```

Or install only what you need:

```bash
pip install docuflow[pdf,llm]      # pdfplumber parser + LLM extraction
pip install docuflow[ocr,llm]      # Tesseract OCR + LLM extraction
pip install docuflow[docling,llm]  # Docling parser (best quality) + LLM
pip install docuflow[privacy]      # PII anonymization via Presidio
```

Requires Python >= 3.11.

## Quick Start

```python
from pydantic import BaseModel
from docuflow import extract

class Invoice(BaseModel):
    supplier_name: str
    invoice_number: str
    total: float

result = extract("invoice.pdf", schema=Invoice)
print(result.data)                          # {"supplier_name": "Acme", "total": 1234.56}
print(result.fields["total"].confidence)    # 0.92
print(result.fields["total"].evidence[0])   # page 0, bbox, source text
```

## Features

### Parsing
- **7 parsers**: pdfplumber (native PDFs), Tesseract OCR (scanned docs), Docling (tables/layout), Smart (auto per-page), Azure Document Intelligence, AWS Textract, Google Document AI
- **Permissive licensing throughout**: every dependency is MIT/BSD/Apache-2.0 — no copyleft (AGPL/GPL) anywhere in the tree
- Every parser produces blocks with bounding boxes for evidence grounding

### Extraction
- **3 extraction types**: text (parser → LLM), vision (images → vision LLM), hybrid (both in parallel)
- **Single or multi-agent**: multi mode runs N parallel LLM calls at varied temperatures with a decider
- **Domain context**: tell the LLM your industry for better extraction
- **JSON reliability**: JSON mode, concrete examples, auto-retry on parse failure

### Evidence & Confidence
- Every field links to source text, page number, and word-precise bounding boxes (multi-line and cross-page highlights supported)
- **Two independent confidence scores** — never the LLM's self-reported confidence:
  - **OCR confidence** (from the parser): did we *read* the characters on the page correctly? Document-level and per-field, matched back from the extracted value to the OCR words
  - **LLM consensus** (from multi-instance extraction): did independent LLM runs *interpret* the document the same way? The signal that matters when no parser is used (vision/hybrid)
- Both are optional and never break the pipeline: no OCR → no OCR score; single instance → no consensus
- **Token usage & cost**: every result reports prompt/completion tokens, call count, and litellm-priced cost
- Full provenance chain: parser → model → evidence → validation → review → correction

### Review
- **6 built-in rules**: confidence thresholds, field presence, validation errors, evidence checks
- **LLM reviewers**: prompt-driven agents that review extractions and return Approved/Not Approved
- **Human corrections**: correct fields with audit trail, approve/reject with timestamp

### Privacy
- PII detection and anonymization before LLM calls via Presidio
- Modes: redact, mask, pseudonymize (reversible), hash
- Image redaction via OCR bounding boxes
- Fail-closed: pipeline stops if anonymization fails

### Portable Workflow Config

Define your entire extraction workflow in a single YAML file — schema, parser, model, validation, review rules — and run it without writing Python:

```yaml
name: invoice-extraction
schema:
  supplier_name: {type: str, required: true, description: "Supplier"}
  total: {type: float, required: true, description: "Total amount"}
parser: smart
model: openai/gpt-4o
extraction_mode: multi
validation:
  - required_fields: [supplier_name, total]
review:
  - overall_confidence_below: 0.7
```

```python
from docuflow import run_workflow

result = run_workflow("invoice.yaml", "invoice.pdf")
```

Export an existing pipeline to share with others:

```python
yaml_str = pipeline.export_yaml(Invoice, name="invoice")
```

### Serve & Dockerize

Document extraction is often one step in a larger workflow built in multiple languages. Wrap any workflow config as an HTTP microservice:

```bash
pip install docuflow[serve]

# Local development server
docuflow serve workflow.yaml --port 8000

# Generate a Docker deployment
docuflow dockerize workflow.yaml --output ./deploy
cd deploy && docker compose up --build
```

Three endpoints: `GET /health`, `GET /schema`, `POST /extract` (file upload → structured data + quality score). Call from any language — curl, JavaScript, Java, Go.

### Production Tools
- **Batch processing**: process folders of documents, get summary reports, export to CSV/DataFrame
- **Workflow routing**: mixed document streams auto-classified and dispatched to the right workflow (`WorkflowRouter` / `docuflow route`); unmatched documents are surfaced, never force-extracted
- **Document comparison**: field-by-field diff across multiple documents
- **Document search**: find text across pages with spatial location
- **Screenshots**: render pages as PNGs for review UIs
- **Quality monitoring**: per-result quality reports, append-only JSONL quality log with tag filtering
- **Local storage**: persist documents, extractions, traces with partial-save on failure

### CLI

```bash
docuflow run invoice.yaml invoice.pdf --output result.json
docuflow extract invoice.pdf --schema invoice
docuflow extract-folder ./invoices --schema invoice --output results.csv
docuflow route routes.yaml ./inbox --output results.csv
docuflow serve workflow.yaml --port 8000
docuflow dockerize workflow.yaml --output ./deploy --with-storage
docuflow screenshot document.pdf -o ./pages
docuflow templates list
```

## Documentation

See the [Complete User Guide](docs/guide.md) for in-depth documentation of every feature, with code examples.
