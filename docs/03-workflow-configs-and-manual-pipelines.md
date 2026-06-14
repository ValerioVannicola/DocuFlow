# Workflow Configs And Manual Pipelines

DocuFlow has two configurable workflow layers:

- Portable YAML workflows through `WorkflowConfig`, `load_workflow_config()`, and `run_workflow()`.
- Manual Python pipelines through `Pipeline` and explicit workflow steps.

Use YAML when you want a portable artifact that can be run by Python, CLI, HTTP serving, Docker,
or routing. Use manual pipelines when application code needs full control over individual steps.

## YAML Workflow Files

Minimal workflow:

```yaml
name: invoice-extraction
schema:
  supplier_name:
    type: str
    required: true
    description: Supplier name
  total:
    type: float
    required: true
    description: Total amount including tax
parser: smart
model: openai/gpt-4o
```

Run it:

```python
from docuflow import run_workflow

result = run_workflow("invoice.yaml", "invoice.pdf")
```

Or via CLI:

```bash
docuflow run invoice.yaml invoice.pdf --output result.json
```

## `WorkflowConfig`

Import:

```python
from docuflow.workflow_config import WorkflowConfig
```

Model fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | `"workflow"` | Workflow name. Also used when building the dynamic schema class. |
| `version` | `str` | `"1.0"` | Workflow version string. |
| `description` | `str` | `""` | Human-readable description. Used by serving/router docs. |
| `schema` | `dict[str, Any]` | `{}` | Field definitions used to build a Pydantic schema. Internally stored as `schema_`. |
| `parser` | `str \| dict` | `"pdfplumber"` | Parser string or parser config dict. |
| `model` | `str` | `"openai/gpt-4o"` | LiteLLM model string. |
| `extraction_type` | `str` | `"text"` | `"text"`, `"vision"`, `"hybrid"`, or `"auto"`. |
| `extraction_mode` | `str` | `"single"` | `"single"` or `"multi"`. |
| `escalation` | `dict \| None` | `None` | Auto-mode vision escalation config. |
| `verification` | `dict \| None` | `None` | Zoom-and-verify config. |
| `schema_shards` | `int \| None` | `None` | Number of schema shards for wide text schemas. |
| `n_instances` | `int` | `5` | Candidate count for multi extraction. |
| `temperatures` | `list[float] \| None` | `None` | Candidate temperatures for multi extraction. |
| `vision_dpi` | `int \| None` | `None` | DPI override for rendered page images. |
| `context` | `str \| None` | `None` | Domain instructions passed into extraction prompts. |
| `validation` | `list[dict]` | `[]` | Validation rules. |
| `review` | `list[dict]` | `[]` | Review rules. |
| `privacy` | `dict \| None` | `None` | Privacy policy config. |
| `storage` | `str \| dict \| None` | `None` | Storage backend config. |
| `llm` | `dict \| None` | `None` | Extra LiteLLM adapter kwargs. |
| `quality_threshold` | `float` | `0.7` | Intended quality threshold value for workflow consumers. |

### Schema Field Definitions

Each entry under `schema:` defines one Pydantic field.

```yaml
schema:
  invoice_number:
    type: str
    required: true
    description: Invoice reference number
  currency:
    type: str
    default: EUR
    description: ISO currency code
```

Supported scalar `type` values:

| YAML type | Python type |
| --- | --- |
| `str`, `string` | `str` |
| `int`, `integer` | `int` |
| `float`, `number` | `float` |
| `bool`, `boolean` | `bool` |
| `date` | `datetime.date` |
| `datetime` | `datetime.datetime` |

Supported structured types:

```yaml
schema:
  line_items:
    type: list
    item_fields:
      description: {type: str, required: true}
      quantity: {type: float, required: true}
      amount: {type: float, required: true}

  supplier:
    type: object
    fields:
      name: {type: str, required: true}
      vat_number: {type: str, required: false}
```

For list fields without `item_fields`, use `item_type`:

```yaml
tags:
  type: list
  item_type: str
```

Required/default behavior:

- `required: true` makes the field required.
- `required: false` with no `default` makes the field optional with default `None`.
- `default` sets the Pydantic default.
- `description` is passed to Pydantic `Field(description=...)` and the extraction prompt.

### Parser Config

Parser can be a string:

```yaml
parser: smart
```

Or a dict:

```yaml
parser:
  type: tesseract
  languages: [eng]
  dpi: 300
  preprocess: []
```

Supported `type` values and keys:

| `type` | Keys |
| --- | --- |
| `pdfplumber` | None. |
| `tesseract` | `languages`, `dpi`, `preprocess`. |
| `docling` | None. |
| `smart` | `languages`, `dpi`, `min_text_length`. |
| `azure-di` | `endpoint`, `key`, `model`. |
| `textract` | `region`, `dpi`. |
| `google-docai` | `project`, `location`, `processor_id`. |

### Validation Config

`WorkflowConfig.build_validators()` supports:

```yaml
validation:
  - required_fields: [supplier_name, total]
  - evidence_required: [total]
  - type_validation: true
```

Mapping:

| YAML key | Builds |
| --- | --- |
| `required_fields` | `RequiredFields(fields)` |
| `evidence_required` | `EvidenceRequired(fields)` |
| `type_validation` | `TypeValidation()` |

### Review Config

`WorkflowConfig.build_review_rules()` supports:

```yaml
review:
  - overall_confidence_below: 0.7
  - field_confidence_below: {total: 0.8}
  - any_field_confidence_below: 0.6
  - has_validation_errors: true
  - field_missing: [total, invoice_number]
  - no_evidence: [total]
  - llm_reviewer:
      name: financial_auditor
      prompt: Check whether totals are mathematically consistent.
      model: openai/gpt-4o
```

Mapping:

| YAML key | Builds |
| --- | --- |
| `overall_confidence_below` | `OverallConfidenceBelow(threshold)` |
| `field_confidence_below` | `FieldConfidenceBelow(fields)` |
| `any_field_confidence_below` | `AnyFieldConfidenceBelow(threshold)` |
| `has_validation_errors` | `HasValidationErrors()` |
| `field_missing` | `FieldMissing(fields)` |
| `no_evidence` | `NoEvidence(fields)`; if value is `true`, checks all fields. |
| `llm_reviewer` | `LLMReviewer(name, prompt, LiteLLMAdapter(model=...))` |

### Privacy Config

```yaml
privacy:
  provider: presidio
  language: en
  mode: pseudonymize
  reversible: true
  fail_closed: true
  mapping_store:
    path: ./.docuflow_mappings
```

Supported keys:

| Key | Description |
| --- | --- |
| `provider` | `"presidio"` or a dict. Dict supports `language` and `model`. |
| `language` | Shortcut language for `provider: presidio`. |
| `mode` | `"redact"`, `"mask"`, `"pseudonymize"`, `"hash"`. |
| `reversible` | Requires `mode: pseudonymize`. |
| `entities` | Presidio entity list. |
| `fail_closed` | Fail the pipeline if anonymization fails. |
| `score_threshold` | Minimum Presidio confidence. |
| `log_scrubbing` | Policy flag for scrubbed logging. |
| `mapping_store` | String path or dict with `path`. |

### Storage Config

```yaml
storage: local
```

Or:

```yaml
storage:
  type: local
  path: ./output
```

Supported built-in storage type: `local`.

### LLM Config

The `llm:` block is passed to `LiteLLMAdapter`.

```yaml
llm:
  max_retries: 5
  prompt_caching: true
  timeout: 60
```

Recognized explicitly by `DocumentPipeline`:

- `max_retries`
- `api_key`

All other keys are passed through to LiteLLM.

## Loading Workflow Configs

```python
from docuflow.workflow_config import load_workflow_config

config = load_workflow_config("invoice.yaml")
```

Signature:

```python
load_workflow_config(source: str | pathlib.Path | dict) -> WorkflowConfig
```

Parameters:

| Parameter | Description |
| --- | --- |
| `source` | YAML path, `Path`, or config dict. |

Returns: `WorkflowConfig`.

## Running Workflows

### `run_workflow()`

Top-level sync import:

```python
from docuflow import run_workflow
```

Actual sync implementation: `run_workflow_sync()`.

Signature:

```python
run_workflow(
    config: str | Path | dict | WorkflowConfig,
    path: str,
) -> ExtractionResult
```

### `run_workflow_async()`

```python
from docuflow import run_workflow_async

result = await run_workflow_async("invoice.yaml", "invoice.pdf")
```

Async signature:

```python
await run_workflow_async(
    config: str | Path | dict | WorkflowConfig,
    path: str,
) -> ExtractionResult
```

Parameters:

| Parameter | Description |
| --- | --- |
| `config` | YAML path, config dict, or already validated `WorkflowConfig`. |
| `path` | Document file path. |

## `WorkflowConfig` Methods

### `parser_type`

Property returning a string parser type. If `parser` is a dict, returns `parser["type"]`
or `"pdfplumber"` if missing.

### `build_schema()`

```python
schema_cls = config.build_schema()
```

Builds a Pydantic schema class from the YAML `schema:` block.

### `build_validators()`

Returns a list of validator objects from `validation:`.

### `build_review_rules()`

Returns a list of review rule objects from `review:`.

### `build_privacy()`

Returns a `PrivacyPolicy` or `None`.

### `build_pipeline()`

```python
pipeline = config.build_pipeline()
```

Builds a `DocumentPipeline` with parser, model, extraction settings, validators, review rules,
privacy, storage, and LLM kwargs from the config.

## Exporting Workflows

Imports:

```python
from docuflow.workflow_config import export_config, export_yaml
```

### `export_config()`

Signature:

```python
export_config(
    pipeline: Any,
    schema: type[pydantic.BaseModel],
    name: str = "workflow",
    version: str = "1.0",
    description: str = "",
) -> dict[str, Any]
```

Exports a `DocumentPipeline` plus schema into a workflow config dict.

### `export_yaml()`

Signature:

```python
export_yaml(
    pipeline: Any,
    schema: type[pydantic.BaseModel],
    name: str = "workflow",
    version: str = "1.0",
    description: str = "",
) -> str
```

Exports the same config as YAML text.

Example:

```python
from docuflow.workflow_config import export_yaml

yaml_str = export_yaml(pipeline, Invoice, name="invoice")
```

Export coverage:

- Schema scalar fields.
- Parser strings/configs where recognized.
- Model, extraction type/mode, escalation, verification, sharding.
- `n_instances`, `temperatures`, `context`.
- `RequiredFields`, `EvidenceRequired`.
- Built-in review rules except LLM reviewers.
- LLM kwargs and local storage config.

## Manual Pipelines

Manual pipelines let you compose steps directly.

```python
from docuflow.workflow import Pipeline, Ingest, Parse, Extract, Validate, Review, Store

pipeline = Pipeline([
    Ingest(path="invoice.pdf"),
    Parse(parser="smart"),
    Extract(schema=Invoice, llm=my_llm),
    Validate(validators=[RequiredFields(["total"])]),
    Review(rules=[OverallConfidenceBelow(0.7)]),
    Store(storage=LocalDocumentStore("./output")),
])

pipeline_result = pipeline.run_sync()
result = pipeline_result.state.extraction_result
```

`result` is the same full `ExtractionResult` returned by `extract()` and `DocumentPipeline`.
Use it for:

- `result.data` for flat extracted values
- `result.fields[...]` for confidence, evidence, trust, OCR, consensus, verification, and validation
- `result.usage`, `result.review_status`, `result.review_reasons`, `result.review_verdicts`
- `result.corrections`, `result.validation_errors`, `result.escalated`, `result.raw_text`
- `result.provenance(field_name)` for audit-style field history

## `Pipeline`

Import:

```python
from docuflow.workflow import Pipeline
```

Constructor:

```python
Pipeline(steps: list[PipelineStep])
```

Methods:

```python
await pipeline.run(
    input_path: str | None = None,
    schema: type[pydantic.BaseModel] | None = None,
    **kwargs: Any,
) -> PipelineResult
```

```python
pipeline.run_sync(
    input_path: str | None = None,
    schema: type[pydantic.BaseModel] | None = None,
    **kwargs: Any,
) -> PipelineResult
```

Parameters:

| Parameter | Description |
| --- | --- |
| `input_path` | Optional path placed into pipeline state metadata as `input_path`. `Ingest(path=None)` reads it. |
| `schema` | Optional schema class placed into metadata as `schema`. Extraction steps read it when no schema is set on the step. |
| `**kwargs` | Extra metadata available to steps through `state.metadata`. |

### `PipelineResult`

Dataclass fields:

| Field | Type | Description |
| --- | --- | --- |
| `state` | `PipelineState` | Final pipeline state. |
| `trace` | `Trace` | Execution trace. |
| `duration_ms` | `float` | Total runtime in milliseconds. |
| `success` | `bool` | True when state status is completed. |
| `errors` | `list[str]` | Step or pipeline errors. |

## Workflow Steps

All steps implement:

```python
async def execute(state: PipelineState) -> PipelineState
```

### `Ingest`

```python
Ingest(path: str | None = None)
```

| Parameter | Description |
| --- | --- |
| `path` | Document path. If omitted, reads `state.metadata["input_path"]`. |

Creates `state.document` by ingesting the local file.

### `Parse`

```python
Parse(parser: Any = None)
```

| Parameter | Description |
| --- | --- |
| `parser` | Parser object or parser string. `None` behaves like `"pdfplumber"`. |

Supported strings: `"pdfplumber"`, `"tesseract"`, `"docling"`, `"smart"`, `"azure-di"`,
`"textract"`, `"google-docai"`.

### `Anonymize`

```python
Anonymize(policy: Any = None)
```

| Parameter | Description |
| --- | --- |
| `policy` | Usually a `PrivacyPolicy`. If `None`, step is a no-op. |

Anonymizes `state.document.raw_text` and page text. If policy `fail_closed=True`, failures
mark the pipeline failed.

### `Extract`

```python
Extract(
    schema: type[BaseModel] | None = None,
    llm: Any = None,
    mode: str = "single",
    n_instances: int = 5,
    temperatures: list[float] | None = None,
    context: str | None = None,
    schema_shards: int | None = None,
)
```

| Parameter | Description |
| --- | --- |
| `schema` | Pydantic schema. If omitted, reads `state.metadata["schema"]`. |
| `llm` | LLM adapter object implementing `complete()`. |
| `mode` | `"single"` or `"multi"`. |
| `n_instances` | Number of candidate calls in multi mode. |
| `temperatures` | Candidate temperatures. |
| `context` | Domain instructions. |
| `schema_shards` | Number of schema shards for text extraction. |

Requires a parsed document.

### `ExtractVision`

```python
ExtractVision(
    schema: type[BaseModel] | None = None,
    llm: Any = None,
    mode: str = "single",
    n_instances: int = 5,
    temperatures: list[float] | None = None,
    dpi: int = DEFAULT_DPI,
    context: str | None = None,
)
```

Reads the original document as rendered images. Do not put `Parse` before this step.

### `ExtractHybrid`

```python
ExtractHybrid(
    schema: type[BaseModel] | None = None,
    llm: Any = None,
    n_instances: int = 5,
    temperatures: list[float] | None = None,
    dpi: int = DEFAULT_DPI,
    context: str | None = None,
)
```

Runs hybrid extraction directly from the original file. Do not put `Parse` before this step.

### `ExtractAuto`

```python
ExtractAuto(
    schema: type[BaseModel] | None = None,
    llm: Any = None,
    mode: str = "single",
    n_instances: int = 5,
    temperatures: list[float] | None = None,
    dpi: int = DEFAULT_DPI,
    context: str | None = None,
    policy: Any = None,
    allow_escalation: bool = True,
)
```

| Parameter | Description |
| --- | --- |
| `policy` | Escalation policy object or config already resolved by caller. |
| `allow_escalation` | Set false to suppress vision escalation, usually when privacy is configured. |

Requires a parsed document and decides whether to use text extraction or vision/hybrid escalation.

### `VerifyFields`

```python
VerifyFields(
    schema: type[BaseModel] | None = None,
    llm: Any = None,
    policy: Any = None,
)
```

Runs zoom-and-verify after extraction and before review.

### `Validate`

```python
Validate(validators: list | None = None)
```

Runs validators and updates `result.validation_errors`, field validation statuses, and field errors.

### `Review`

```python
Review(rules: list | None = None)
```

Runs sync review rules and async LLM reviewers. Updates `result.needs_review`,
`result.review_reasons`, `result.review_verdicts`, and token usage for LLM reviewers.

### `Store`

```python
Store(storage: Any = None)
```

Saves document, extraction result, and trace through the storage object. If storage is `None`,
the step is a no-op.

## Pipeline Failure Behavior

If a step raises or sets `state.status = "failed"`:

- The pipeline stops.
- `PipelineResult.success` is false.
- Errors are available on `PipelineResult.errors` and `PipelineResult.state.errors`.
- If a `Store` step with storage exists anywhere in the pipeline, partial document/result/trace
  state is saved where possible.
