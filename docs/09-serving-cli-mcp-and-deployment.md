# Serving, CLI, MCP, And Deployment

This file documents DocuFlow's HTTP service helpers, Docker deployment generator, CLI commands,
and MCP server tools.

## HTTP Serving

DocuFlow can expose any workflow config as a FastAPI app.

Install:

```bash
pip install docuflow[serve]
```

Example:

```python
from docuflow.serve import create_app
from docuflow.workflow_config import load_workflow_config

config = load_workflow_config("workflow.yaml")
app = create_app(config)
```

## `create_app()`

Import:

```python
from docuflow.serve import create_app
```

Signature:

```python
create_app(config: WorkflowConfig) -> fastapi.FastAPI
```

Parameters:

| Parameter | Description |
| --- | --- |
| `config` | Validated `WorkflowConfig`. |

Returns a FastAPI app serving one workflow.

### Endpoints

#### `GET /health`

Returns:

```json
{
  "status": "ok",
  "workflow": "workflow-name",
  "version": "1.0",
  "model": "openai/gpt-4o",
  "parser": "smart"
}
```

#### `GET /schema`

Returns:

```json
{
  "workflow": "workflow-name",
  "fields": {
    "field_name": {
      "type": "str",
      "required": true,
      "description": "..."
    }
  }
}
```

#### `POST /extract`

Multipart upload endpoint.

Input:

- Form field: `file`
- Type: uploaded file

Behavior:

- Saves upload to a temporary file.
- Builds pipeline and schema from the workflow config.
- Runs synchronous extraction.
- Deletes the temporary file.
- Runs `quality_report(result)`.
- Returns the full final `ExtractionResult` JSON, including `data`, `fields`, `confidence`,
  `confidence_score`, `consensus_score`, `ocr`, `usage`, `escalated`, `review_status`, `validation_errors`, `corrections`,
  `trace_id`, `model_name`, `parser_name`, and `raw_text`, plus:
  - `quality_score`
  - `quality_ok`

## `run_server()`

Import:

```python
from docuflow.serve import run_server
```

Signature:

```python
run_server(
    config_source: str | pathlib.Path | dict,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `config_source` | Required | Workflow YAML path, `Path`, or dict. |
| `host` | `"0.0.0.0"` | Host passed to Uvicorn. |
| `port` | `8000` | Port passed to Uvicorn. |

CLI equivalent:

```bash
docuflow serve workflow.yaml --host 0.0.0.0 --port 8000
```

## Docker Deployment Generation

DocuFlow can generate a deployment directory for a workflow config.

```python
from docuflow.dockerize import generate_deployment

generate_deployment("workflow.yaml", "./deploy", port=8000, with_storage=True)
```

## `generate_deployment()`

Import:

```python
from docuflow.dockerize import generate_deployment
```

Signature:

```python
generate_deployment(
    config_source: str | pathlib.Path,
    output_dir: str | pathlib.Path,
    port: int = 8000,
    with_storage: bool = False,
) -> pathlib.Path
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `config_source` | Required | Workflow YAML path. Must exist. |
| `output_dir` | Required | Directory to create/update. |
| `port` | `8000` | Host port in generated `docker-compose.yml`. |
| `with_storage` | `False` | Add a persistent Docker volume mounted at `/data`. |

Generated files:

```text
Dockerfile
server.py
workflow.yaml
requirements.txt
docker-compose.yml
.dockerignore
```

Generated requirements include `docuflow[...]` extras inferred from the workflow:

| Workflow feature | Added extras/deps |
| --- | --- |
| Always | `llm`, `serve` |
| `parser: auto` | `pdf`, `ocr`, `docling`, system `tesseract-ocr` |
| `parser: pdfplumber` | `pdf` |
| `parser: smart` | `pdf`, `ocr`, system `tesseract-ocr` |
| `parser: tesseract` | `pdf`, `ocr`, system `tesseract-ocr` |
| `parser: docling` | `docling` |
| `parser: azure-di` | `azure` |
| `parser: textract` | `aws`, `pdf` |
| `parser: google-docai` | `gcp` |
| `extraction_type: vision`, `hybrid`, or `auto` | `pdf`; also `ocr` and system Tesseract in current generator logic |
| `privacy:` configured | `privacy` |

The generated `docker-compose.yml` exposes provider env vars:

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

CLI equivalent:

```bash
docuflow dockerize workflow.yaml --output ./deploy --port 8000 --with-storage
```

## CLI Overview

Main command:

```bash
docuflow --help
docuflow --version
```

Commands:

| Command | Purpose |
| --- | --- |
| `extract` | Extract one document with a schema. |
| `extract-folder` | Batch extract documents from a folder. |
| `run` | Run a workflow YAML config on one document. |
| `screenshot` | Render PDF pages to images. |
| `serve` | Start HTTP service for a workflow YAML config. |
| `dockerize` | Generate Docker deployment files. |
| `route` | Classify and route mixed documents through workflows. |
| `templates list` | List templates. |
| `templates show` | Show template YAML. |
| `templates init` | Copy built-in template into a project/user folder. |

## `docuflow extract`

```bash
docuflow extract FILE_PATH --schema invoice --model openai/gpt-4o --output result.json --store local
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `FILE_PATH` | Required | Document path. |
| `--schema`, `-s` | Required | Schema template name or dotted Python path. |
| `--model`, `-m` | `"openai/gpt-4o"` | LLM model. |
| `--output`, `-o` | `None` | Output JSON path. If omitted, prints JSON to stdout. |
| `--store` | `None` | Storage backend, for example `"local"`. |

Internally calls `extract_sync(file_path, schema=schema_cls, model=model, storage=store)`.

## `docuflow extract-folder`

```bash
docuflow extract-folder ./invoices --schema invoice --parser smart --output results.csv
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `FOLDER_PATH` | Required | Folder to scan. |
| `--schema`, `-s` | Required | Schema template name or dotted Python path. |
| `--model`, `-m` | `"openai/gpt-4o"` | LLM model. |
| `--parser`, `-p` | `"auto"` | Parser string. `"auto"` selects from the input type. |
| `--output`, `-o` | `None` | CSV output file. |
| `--pattern` | `"**/*.pdf"` | Glob pattern inside folder. |
| `--concurrency`, `-c` | `5` | Max concurrent extractions. |

## `docuflow run`

```bash
docuflow run workflow.yaml invoice.pdf --output result.json
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `CONFIG_PATH` | Required | Workflow YAML path. |
| `FILE_PATH` | Required | Document path. |
| `--output`, `-o` | `None` | Output JSON path. If omitted, prints JSON to stdout. |

## `docuflow screenshot`

```bash
docuflow screenshot file.pdf --output ./pages --dpi 200 --pages 0,1,2
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `FILE_PATH` | Required | PDF path. |
| `--output`, `-o` | Required | Output directory. |
| `--dpi` | `DEFAULT_DPI` | Render DPI. |
| `--pages` | `None` | Comma-separated zero-based page numbers. Empty renders all pages. |

## `docuflow serve`

```bash
docuflow serve workflow.yaml --host 0.0.0.0 --port 8000
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `CONFIG_PATH` | Required | Workflow YAML path. |
| `--host` | `"0.0.0.0"` | Bind host. |
| `--port`, `-p` | `8000` | Bind port. |

Requires `docuflow[serve]`.

## `docuflow dockerize`

```bash
docuflow dockerize workflow.yaml --output ./deploy --port 8000 --with-storage
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `CONFIG_PATH` | Required | Workflow YAML path. |
| `--output`, `-o` | `"./deploy"` | Deployment directory. |
| `--port`, `-p` | `8000` | Host port in compose file. |
| `--with-storage` | `False` | Add persistent volume. |

## `docuflow route`

```bash
docuflow route routes.yaml ./inbox --output results.csv --pattern "**/*.pdf" --concurrency 5
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `ROUTES_PATH` | Required | Routes YAML path. |
| `INPUT_PATH` | Required | File or folder. |
| `--output`, `-o` | `None` | CSV output path. |
| `--pattern` | `"**/*.pdf"` | Folder glob pattern. |
| `--concurrency`, `-c` | `5` | Concurrent documents. |

Routes config:

```yaml
model: gemini/gemini-2.5-flash
workflows:
  - name: invoice
    description: supplier invoices
    workflow: workflows/invoice.yaml
```

## Template CLI

### `docuflow templates list`

Lists all visible templates.

### `docuflow templates show NAME`

Prints the YAML definition for `NAME`.

### `docuflow templates init NAME`

```bash
docuflow templates init invoice --dir docuflow_templates
```

Arguments/options:

| Name | Default | Description |
| --- | --- | --- |
| `NAME` | Required | Built-in template name. |
| `--dir` | `docuflow_templates` | Target directory. |

## MCP Server

Install:

```bash
pip install docuflow[mcp]
```

Run:

```bash
docuflow-mcp
```

Or:

```bash
python -m docuflow.mcp_server
```

The server name is `DocuFlow`. It exposes the following tools.

## MCP Tools

### `extract_document`

```python
extract_document(
    file_path: str,
    schema_name: str = "invoice",
    parser: str = "auto",
    model: str = "openai/gpt-4o",
    extraction_mode: str = "single",
    n_instances: int = 5,
    context: str = "",
) -> str
```

Returns the full extraction result JSON payload described in `06-results-and-data-models.md`.

### `extract_with_vision`

```python
extract_with_vision(
    file_path: str,
    schema_name: str = "invoice",
    model: str = "openai/gpt-4o",
    extraction_mode: str = "single",
    n_instances: int = 5,
) -> str
```

Uses `DocumentPipeline(parser=None, extraction_type="vision")` and returns the same full final
result payload.

### `discover_schema`

```python
discover_schema(
    file_path: str,
    parser: str = "auto",
    model: str = "openai/gpt-4o",
) -> str
```

Returns JSON with:

- `document_type`
- `description`
- `fields`
- `yaml_template`

### `compare_documents`

```python
compare_documents(
    file_paths: list[str],
    schema_name: str = "invoice",
    parser: str = "auto",
    model: str = "openai/gpt-4o",
) -> str
```

Returns comparison result JSON.

### `process_batch`

```python
process_batch(
    folder_path: str,
    schema_name: str = "invoice",
    parser: str = "auto",
    model: str = "openai/gpt-4o",
    pattern: str = "**/*.pdf",
    concurrency: int = 5,
) -> str
```

Returns summary JSON with totals, average confidence, review reasons, and document summaries.
Each successful document summary can be correlated with the full `ExtractionResult` stored in
`result` when using the Python API or retrieved later with `get_extraction_result()`.

### `list_templates`

```python
list_templates() -> str
```

Returns JSON list of templates with `name`, `version`, `source`, and `description`.

### `show_template`

```python
show_template(name: str) -> str
```

Returns YAML template content.

### `search_in_document`

```python
search_in_document(
    file_path: str,
    query: str,
    parser: str = "auto",
) -> str
```

Parses the document with the source-aware `auto` behavior, or with an explicit parser string,
then returns `SearchResult` JSON. Text/email inputs can be searched without a parser.

### `get_pending_reviews`

```python
get_pending_reviews(store_path: str = "./.docuflow_store") -> str
```

Returns JSON list of document ids pending review.

### `get_extraction_result`

```python
get_extraction_result(
    document_id: str,
    store_path: str = "./.docuflow_store",
) -> str
```

Returns stored full extraction result JSON or an error JSON object.

### `correct_field`

```python
correct_field(
    document_id: str,
    field_name: str,
    new_value: str,
    corrected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored result, applies `ExtractionResult.correct_field()`, saves it, and returns
correction summary JSON.

Note: `new_value` is passed as a string by this MCP tool.

### `approve_document`

```python
approve_document(
    document_id: str,
    approved_by: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored result, approves it, saves it, and returns review status JSON.

### `reject_document`

```python
reject_document(
    document_id: str,
    rejected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored result, rejects it, saves it, and returns review status JSON.

### `get_pending_fills`

```python
get_pending_fills(store_path: str = "./.docuflow_store") -> str
```

Returns a JSON list of document ids whose PDF form fill was prepared with `review=True`
and still awaits human approval before the output PDF is written. See the
"Review & Approval" section of `11-pdf-form-filling.md`.

### `edit_fill_field`

```python
edit_fill_field(
    document_id: str,
    field_name: str,
    new_value: str,
    corrected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored `FillingResult`, applies `FillingResult.edit_field(value=...)` to change a
planned fill value before the PDF is committed, saves it, and returns JSON with the field's
old value, new value, and correction record.

Note: `new_value` is passed as a string by this MCP tool. Only value edits are supported here;
placement edits (`bbox`, `page_number`, `font_size`, `align`) use the Python API.

### `approve_fill`

```python
approve_fill(
    document_id: str,
    approved_by: str = "",
    commit: bool = True,
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored result, approves it, and — when `commit` is True (the default) — writes the
output PDF via `commit_fill_async()`. Saves the result and returns JSON with the review
status, the `committed` flag, and the `output_path`.

### `reject_fill`

```python
reject_fill(
    document_id: str,
    rejected_by: str = "",
    reason: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Loads a stored result, rejects it, saves it, and returns review status JSON. The output PDF
is not written.

### `split_document`

```python
split_document(
    file_path: str,
    sections: str,
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: str = "",
) -> str
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | Path to the PDF document. |
| `sections` | Required | JSON array of section objects, each with `"name"` and `"description"`. Example: `[{"name": "body", "description": "Main terms"}, {"name": "exhibits", "description": "Attached exhibits"}]`. |
| `model` | `"gemini/gemini-2.5-flash"` | LiteLLM model string. |
| `deep` | `false` | When `true`, each section also includes `confidence` and `evidence`. |
| `allow_overlap` | `true` | When `true`, a page may appear in multiple sections. |
| `split_rules` | `""` | Optional prompt overriding default splitting logic. |
| `pages` | `""` | Comma-separated 0-based page indices to process. Empty means all pages. |

Returns `SplitResult` JSON with `page_map` (section → pages), per-section confidence and
evidence (deep mode), usage, warnings, and errors. See `12-document-splitting.md`.

### `fill_docx_form`

```python
fill_docx_form(
    file_path: str,
    data: str,
    output_path: str = "",
    strategy: str = "auto",
    flatten: bool = False,
    review: bool = False,
    document_id: str = "",
    store_path: str = "./.docuflow_store",
) -> str
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | Path to the input `.docx` file. |
| `data` | Required | JSON string of field values to fill (keys match content control tags or aliases). |
| `output_path` | `""` | Where to save the filled DOCX. Defaults to `<stem>-filled.docx`. |
| `strategy` | `"auto"` | `"auto"` (detect) or `"content_controls"` (Word SDT). |
| `flatten` | `false` | Remove SDT wrappers after filling (content_controls only). |
| `review` | `false` | When `true`, plan the fill but do not write the file. |
| `document_id` | `""` | Optional document identifier. Used for storage when `review=true`. |
| `store_path` | `"./.docuflow_store"` | Store path when `review=true`. |

Returns `FillingResult` JSON (success, strategy, fields, warnings, errors, review_status).
See `11-pdf-form-filling.md` for the full review/approval workflow.

### `extract_document_metadata`

```python
extract_document_metadata(
    file_path: str,
) -> str
```

Extracts document-level metadata from a PDF or DOCX file: annotation comments, highlights,
hyperlinks, signature fields, and tracked-change revisions. Dispatches on file extension.

Returns `DocumentMetadataResult` JSON with `comments`, `highlights`, `hyperlinks`,
`signatures`, `revisions`, `warnings`, and `errors`.
See `13-document-metadata.md` for the full model reference.

### `screenshot_document`

```python
screenshot_document(
    file_path: str,
    output_dir: str,
    pages: str = "",
    dpi: int = 200,
) -> str
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | PDF path. |
| `output_dir` | Required | Directory to save screenshots. |
| `pages` | `""` | Comma-separated zero-based page numbers. Empty renders all pages. |
| `dpi` | `200` | Render DPI. |

Returns JSON list of generated screenshots.

## Deployment Notes

- Use workflow YAML as the portable deployment artifact.
- Use `docuflow serve` for local or process-manager deployment.
- Use `docuflow dockerize` for container deployment.
- Use MCP when DocuFlow should be called by AI agents as tools.
- Configure LLM provider API keys in the runtime environment.
- Configure cloud OCR provider credentials in the runtime environment or workflow parser config.
