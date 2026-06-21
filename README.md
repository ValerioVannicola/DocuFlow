<p align="center">
  <img src="docs/assets/docuflow-logo.png" alt="DocuFlow logo" width="920">
</p>


#### DocuFlow turns unstructured documents into production-ready data. Unlike typical extraction tools that stop at raw JSON, DocuFlow adds evidence, consensus, verification, validation, and auditability so you can trust, review, and ship the result.


## Why DocuFlow?

Most document extraction tools focus on one part of the problem: parsing a PDF, running OCR, or calling an LLM. In real workflows, that is rarely enough. Teams also need schemas, evidence, trust signals, validation, privacy controls, review steps, corrections, storage, and an audit trail they can rely on.

DocuFlow is a workflow runtime for document extraction and PDF write-back. It combines parsers, OCR, LLMs, validation rules, review logic, consensus, verification, form filling, and deployment options into one reproducible pipeline, so document data can move from messy PDFs into production systems, and trusted data can be written back into forms, with traceability and control.

## What It Can Process

DocuFlow accepts these source types today:

- PDF: `.pdf`
- Images: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.gif`, `.webp`
- Text-like files: `.txt`, `.md`, `.html`, `.htm`, `.csv`, `.json`, `.xml`
- Office documents: `.docx`
- Spreadsheets: `.xlsx`
- Email: `.eml`

## Installation

```bash
pip install docuflow[all]
```

Or install only what you need:

```bash
pip install docuflow[pdf,llm]      # pdfplumber parser + LLM extraction
pip install docuflow[ocr,llm]      # Tesseract OCR + LLM extraction
pip install docuflow[docling,llm]    # Docling parser (best quality) + LLM
pip install docuflow[markitdown,llm] # Markitdown parser (widest format range, no confidence) + LLM
pip install docuflow[forms]          # PDF and DOCX form filling
pip install docuflow[privacy]        # PII anonymization via Presidio
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
print(result.fields["total"].trust_gate)     # True
print(result.fields["total"].evidence[0])   # page 0, bbox, source text
```

## Features

### Parsing
- **8 parsers**: pdfplumber (native PDFs), Tesseract OCR (scanned docs), Docling (tables/layout), Smart (auto per-page), Markitdown (widest format range, no confidence score), Azure Document Intelligence, AWS Textract, Google Document AI
- **Source-aware ingestion**: the default `parser="auto"` accepts PDFs, images, text/Markdown/HTML/CSV/JSON/XML/email files, and Docling-backed Office/spreadsheet documents while still normalizing everything to DocuFlow's `Document` model
- **Permissive licensing throughout**: the dependency set is MIT/BSD/Apache-2.0, with no copyleft packages in the tree
- Every parser produces blocks with bounding boxes for evidence grounding

### Extraction
- **4 extraction types**: text (parser or parserless text → LLM), vision (PDF/image pages → vision LLM), hybrid (both in parallel), and auto (escalate weak OCR to vision)
- **Single or multi-agent**: multi mode runs N parallel LLM calls at varied temperatures with a decider
- **Domain context**: tell the LLM your industry for better extraction
- **JSON reliability**: JSON mode, concrete examples, auto-retry on parse failure

### PDF Form Filling
- **Dedicated write-back API**: `fill_pdf_form()` writes trusted Pydantic data into PDFs and returns `FillingResult`, separate from extraction
- **AcroForm support**: fill existing PDF form fields by Pydantic alias, field name, normalized name, or explicit map
- **Static overlay support**: write values into visual blanks with explicit page/bbox placements, or opt into heuristic/LLM blank detection with `detect_blank_spaces=True`

### Evidence & Confidence
- Every field links to source text, page number, and word-precise bounding boxes (multi-line and cross-page highlights supported)
- **Two independent confidence scores** — never the LLM's self-reported confidence:
  - **OCR confidence** (from OCR): did we *read* the characters on the page correctly? Document-level and per-field, matched back from the extracted value to the OCR words. Produced whenever OCR runs — via an OCR parser (`tesseract`/`smart`/`docling`/cloud) in text mode, **and automatically in vision/hybrid mode**, where DocuFlow OCRs the rendered page images in the background to add bounding boxes and confidence (no parser selection required)
  - **LLM consensus** (from multi-instance extraction): did independent LLM runs *interpret* the document the same way? Especially useful in vision/hybrid mode
- Both are optional and never break the pipeline: with no OCR engine available there is simply no OCR score and no bounding boxes (a warning is emitted) and the run still completes; single instance → no consensus
- **Token usage & cost**: every result reports prompt/completion tokens, call count, and litellm-priced cost
- Full provenance chain: parser → model → evidence → validation → review → correction

### Review
- **6 built-in rules**: trust-gate thresholds, field presence, validation errors, evidence checks
- **LLM reviewers**: prompt-driven agents that review extractions and return Approved/Not Approved
- **Human corrections**: correct fields with audit trail, approve/reject with timestamp

### Privacy
- PII detection and anonymization before LLM calls via Presidio
- Custom-term masking via `DictionaryProvider` (company names, project codes, anything Presidio doesn't know) — no extra dependencies, combine with Presidio via `CompositeProvider`
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

See the [Complete User Guide](guide.md) for in-depth documentation of every feature, with code examples.
