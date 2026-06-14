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
| `--parser`, `-p` | `"pdfplumber"` | Parser string. |
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
    parser: str = "pdfplumber",
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
    parser: str = "pdfplumber",
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
    parser: str = "pdfplumber",
    model: str = "openai/gpt-4o",
) -> str
```

Returns comparison result JSON.

### `process_batch`

```python
process_batch(
    folder_path: str,
    schema_name: str = "invoice",
    parser: str = "pdfplumber",
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
    parser: str = "pdfplumber",
) -> str
```

Parses the document with `pdfplumber`, `tesseract`, `docling`, or `smart`, then returns
`SearchResult` JSON.

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
