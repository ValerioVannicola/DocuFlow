# Batch, Comparison, Routing, Quality, And Eval

This file documents DocuFlow APIs for running extraction across many documents, comparing
versions, routing mixed document streams, measuring quality, and evaluating accuracy.

## Batch Processing

Batch processing runs one pipeline against many files concurrently.

```python
from docuflow import DocumentPipeline, process_batch

pipeline = DocumentPipeline(parser="smart", model="openai/gpt-4o")
report = process_batch(
    files=["inv1.pdf", "inv2.pdf", "inv3.pdf"],
    schema=Invoice,
    pipeline=pipeline,
    concurrency=5,
)
```

### `process_batch()`

Top-level sync import:

```python
from docuflow import process_batch
```

Actual sync implementation: `process_batch_sync()`.

Signature:

```python
process_batch(
    files: list[str],
    schema: type[pydantic.BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> BatchReport
```

### `process_batch_async()`

```python
from docuflow import process_batch_async

report = await process_batch_async(files, Invoice, pipeline, concurrency=5)
```

Async signature:

```python
await process_batch_async(
    files: list[str],
    schema: type[pydantic.BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> BatchReport
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `files` | Required | Document paths to process. |
| `schema` | Required | Pydantic schema class. |
| `pipeline` | Required | Object with `run(path, schema)`, usually `DocumentPipeline`. |
| `concurrency` | `5` | Maximum concurrent document extractions. |

Behavior:

- Each file is processed under an asyncio semaphore.
- Successful results are collected in `report.results`.
- Failed files produce `DocumentSummary(success=False, error=...)`.
- Token usage is aggregated across successful results that report usage.

### `BatchReport`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `total` | `int` | `0` | Number of input files. |
| `succeeded` | `int` | `0` | Successful extractions. |
| `failed` | `int` | `0` | Failed extractions. |
| `needs_review` | `int` | `0` | Successful documents flagged for review. |
| `approved` | `int` | `0` | Successful documents not needing review. |
| `average_confidence` | `float` | `0.0` | Mean confidence across successful documents. |
| `usage` | `TokenUsage \| None` | `None` | Aggregated token usage. |
| `top_review_reasons` | `dict[str, int]` | `{}` | Top review reasons and counts. |
| `field_names` | `list[str]` | `[]` | Union of field names seen in results, ordered by first appearance. |
| `documents` | `list[DocumentSummary]` | `[]` | Per-file summaries. |
| `results` | `list[ExtractionResult]` | `[]` | Successful extraction results. Each one is the full final result object with fields, evidence, confidence, review state, corrections, provenance metadata, and runtime metadata. |

Methods:

```python
report.to_csv() -> str
report.to_dataframe() -> pandas.DataFrame
```

`to_dataframe()` requires `pandas`.

### `DocumentSummary`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `file_path` | `str` | Required | Source file path. |
| `file_name` | `str` | Required | File basename. |
| `document_id` | `str` | `""` | Result document id. |
| `success` | `bool` | `True` | Whether extraction succeeded. |
| `error` | `str` | `""` | Error message for failed files. |
| `confidence` | `float` | `0.0` | Result confidence. |
| `needs_review` | `bool` | `False` | Review flag. |
| `review_reasons` | `list[str]` | `[]` | Review reasons. |
| `data` | `dict` | `{}` | Extracted data. |

## Document Comparison

Use comparison to extract the same schema from multiple documents and see field-by-field
differences.

```python
from docuflow import compare_documents

comparison = compare_documents(
    files=["contract_v1.pdf", "contract_v2.pdf"],
    schema=Contract,
    pipeline=pipeline,
)
```

### `compare_documents()`

Top-level sync import:

```python
from docuflow import compare_documents
```

Signature:

```python
compare_documents(
    files: list[str],
    schema: type[pydantic.BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> ComparisonResult
```

### `compare_documents_async()`

```python
from docuflow import compare_documents_async

comparison = await compare_documents_async(files, Contract, pipeline)
```

Async signature:

```python
await compare_documents_async(
    files: list[str],
    schema: type[pydantic.BaseModel],
    pipeline: Any,
    concurrency: int = 5,
) -> ComparisonResult
```

Parameters are the same as batch processing.

Behavior:

- Failed extractions are skipped.
- The comparison includes all fields seen in successful results.
- Values are compared by string representation for grouping/counts.

### `ComparisonResult`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `schema_name` | `str` | Required | Schema class name. |
| `documents` | `list[str]` | `[]` | File names for successfully extracted documents. |
| `fields` | `dict[str, list[ComparisonCell]]` | `{}` | Per-field cells across documents. |
| `differences` | `dict[str, FieldDifference]` | `{}` | Agreement/difference summary per field. |
| `results` | `list[ExtractionResult]` | `[]` | Successful extraction results. |

### `ComparisonCell`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `document_id` | `str` | Required | Source document id. |
| `file_name` | `str` | Required | Source file name. |
| `value` | `Any` | `None` | Field value. |
| `trust_gate` | `bool` | `False` | Whether the field passed the trust gate. |
| `evidence` | `list[Evidence]` | `[]` | Field evidence. |

### `FieldDifference`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `field_name` | `str` | Required | Field name. |
| `all_agree` | `bool` | `True` | True when all documents have the same stringified value. |
| `unique_values` | `list[Any]` | `[]` | Unique original values in first-seen order. |
| `value_counts` | `dict[str, int]` | `{}` | Counts by stringified value. |
| `summary` | `str` | `""` | Human-readable agreement/difference summary. |

## Workflow Routing

`WorkflowRouter` classifies each file into a registered workflow before extraction.

```python
from docuflow import WorkflowRouter

router = WorkflowRouter()
router.register("invoice", "workflows/invoice.yaml")
router.register(
    "claim",
    pipeline=claims_pipeline,
    schema=ClaimForm,
    description="motor insurance claim forms",
)

report = router.route_sync(files, concurrency=5)
```

Default classifier model:

```python
gemini/gemini-2.5-flash
```

### `WorkflowRouter`

Constructor:

```python
WorkflowRouter(
    model: str = "gemini/gemini-2.5-flash",
    llm: Any = None,
    confidence_threshold: float = 0.5,
    peek_chars: int = 2000,
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | `"gemini/gemini-2.5-flash"` | LiteLLM model for classification when `llm` is not supplied. |
| `llm` | `None` | Optional LLM adapter. |
| `confidence_threshold` | `0.5` | Minimum classifier confidence needed to route. |
| `peek_chars` | `2000` | Characters read from first page text for classification. |

Classification behavior:

- If first-page text has at least 50 non-whitespace characters, routes from text.
- If first-page text is sparse/empty, renders page 0 at low DPI and routes from an image.
- If no workflow clearly matches, the document is returned as unclassified and is not extracted.

### `register()`

```python
router.register(
    name: str,
    workflow: str | pathlib.Path | dict | None = None,
    *,
    pipeline: Any = None,
    schema: Any = None,
    description: str = "",
) -> None
```

Registration modes:

| Mode | Required parameters |
| --- | --- |
| Workflow config | `name`, `workflow` path/dict. |
| Explicit pipeline | `name`, `pipeline`, `schema`. |

If `description` is omitted for explicit pipelines, DocuFlow generates a description from schema
field names. Duplicate names raise `ValueError`.

### `from_config()`

```python
WorkflowRouter.from_config(source: str | pathlib.Path | dict) -> WorkflowRouter
```

Routes config example:

```yaml
model: gemini/gemini-2.5-flash
workflows:
  - name: invoice
    description: supplier invoices with totals and line items
    workflow: workflows/invoices.yaml
  - name: claim
    description: motor insurance claim forms
    workflow: workflows/claims.yaml
```

Relative workflow paths resolve relative to the routes config file.

### `classify()`

```python
await router.classify(file_path: str) -> ClassificationDecision
```

Raises `ValueError` if no workflows are registered.

### `route()` / `route_sync()`

```python
await router.route(files: list[str], concurrency: int = 5) -> RoutedReport
router.route_sync(files: list[str], concurrency: int = 5) -> RoutedReport
```

Runs classification and then matching extraction workflow for each document.

### Routing Models

#### `RegisteredWorkflow`

| Field | Type | Description |
| --- | --- | --- |
| `name` | `str` | Workflow name. |
| `description` | `str` | Classification description. |
| `pipeline` | `Any` | Pipeline object. |
| `schema_cls` | `Any` | Schema class. |

#### `ClassificationDecision`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `workflow` | `str \| None` | `None` | Selected workflow name, or `None`. |
| `confidence` | `float` | `0.0` | Classifier confidence. |
| `reason` | `str` | `""` | Classifier reason or failure reason. |

#### `RoutedResult`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `file_path` | `str` | Required | Source path. |
| `file_name` | `str` | Required | Source basename. |
| `workflow` | `str \| None` | `None` | Selected workflow. |
| `classification_confidence` | `float` | `0.0` | Classifier confidence. |
| `classification_reason` | `str` | `""` | Classifier reason. |
| `success` | `bool` | `False` | Extraction success. |
| `error` | `str` | `""` | Extraction error. |
| `result` | `ExtractionResult \| None` | `None` | Full extraction result for the routed document. |

#### `RoutedReport`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `total` | `int` | `0` | Number of files. |
| `results` | `list[RoutedResult]` | `[]` | Per-file routed results. |
| `usage` | `TokenUsage \| None` | `None` | Classification plus extraction token usage. |

Properties/methods:

```python
report.by_workflow -> dict[str, list[RoutedResult]]
report.unclassified -> list[RoutedResult]
report.failed -> list[RoutedResult]
report.to_csv() -> str
```

## Quality Reports

Quality reports score an extraction or a list of extractions based on completeness, evidence,
source grounding, confidence, auto-acceptance, and corrections.

```python
from docuflow import quality_report

report = quality_report(result, threshold=0.7)
```

### `quality_report()`

Signature:

```python
quality_report(
    results: ExtractionResult | list[ExtractionResult],
    threshold: float = 0.7,
) -> QualityReport
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `results` | Required | One `ExtractionResult` or a list. |
| `threshold` | `0.7` | Minimum score for `report.ok`. |

Single-result score formula:

```text
0.15 * completeness_rate
+ 0.25 * evidence_coverage
+ 0.25 * grounding_rate
+ 0.20 * mean_confidence
+ 0.15 * auto_accept_rate
```

### `QualityReport`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `score` | `float` | `0.0` | Overall score. |
| `completeness_rate` | `float` | `0.0` | Present fields / total fields. |
| `grounding_rate` | `float` | `0.0` | Present fields found in source / present fields. |
| `evidence_coverage` | `float` | `0.0` | Present fields with evidence / present fields. |
| `mean_confidence` | `float` | `0.0` | Average confidence for present fields. |
| `auto_accept_rate` | `float` | `0.0` | Present fields auto-accepted / present fields. |
| `correction_rate` | `float` | `0.0` | Present fields corrected / present fields. |
| `needs_review_count` | `int` | `0` | Number of review reasons for a single result, summed for lists. |
| `field_count` | `int` | `0` | Total field count. |
| `ok` | `bool` | `True` | `score >= threshold`. |
| `warnings` | `list[str]` | `[]` | Human-readable quality warnings. |
| `field_details` | `dict[str, FieldQuality]` | `{}` | Per-field details for single-result reports. Empty for list reports. |
| `n_results` | `int` | `1` | Number of results assessed. |
| `worst_fields` | `list[str]` | `[]` | Lowest quality fields. |

### `FieldQuality`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `found_in_source` | `bool` | `False` | Trust source-found flag. |
| `has_evidence` | `bool` | `False` | Field has evidence. |
| `trust_gate` | `bool` | `False` | Trust gate flag. |
| `corrected` | `bool` | `False` | Field corrected. |
| `missing` | `bool` | `False` | Field value is missing. |
| `warning` | `str` | `""` | Per-field warning label. |

## Quality Logging

### `QualitySnapshot`

```python
from docuflow.quality import QualitySnapshot

snapshot = QualitySnapshot.from_report(report, tags={"schema": "Invoice"})
```

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `snapshot_id` | `str` | UUID | Snapshot id. |
| `timestamp` | `datetime` | `datetime.now()` | Snapshot time. |
| `tags` | `dict[str, str]` | `{}` | User tags. |
| `score` | `float` | `0.0` | Report score. |
| `completeness_rate` | `float` | `0.0` | Report metric. |
| `grounding_rate` | `float` | `0.0` | Report metric. |
| `evidence_coverage` | `float` | `0.0` | Report metric. |
| `mean_confidence` | `float` | `0.0` | Report metric. |
| `auto_accept_rate` | `float` | `0.0` | Report metric. |
| `correction_rate` | `float` | `0.0` | Report metric. |
| `field_count` | `int` | `0` | Report field count. |
| `ok` | `bool` | `True` | Report ok flag. |

### `QualityLog`

```python
from docuflow import QualityLog

log = QualityLog("./quality.jsonl")
snapshot = log.record_sync(report, tags={"schema": "Invoice"})
history = log.history_sync(last_n=50, tags={"schema": "Invoice"})
```

Constructor:

```python
QualityLog(path: str | pathlib.Path)
```

Methods:

```python
await log.record(report: QualityReport, tags: dict[str, str] | None = None) -> QualitySnapshot
log.record_sync(report: QualityReport, tags: dict[str, str] | None = None) -> QualitySnapshot
await log.history(last_n: int | None = None, tags: dict[str, str] | None = None) -> list[QualitySnapshot]
log.history_sync(last_n: int | None = None, tags: dict[str, str] | None = None) -> list[QualitySnapshot]
```

Behavior:

- Appends one JSON object per line.
- `history(..., tags=...)` filters snapshots where all provided tag key/value pairs match.
- `last_n` returns the last N filtered snapshots.

## Eval Harness

The eval harness compares predicted extraction results against ground truth.

Ground truth can be approved/corrected `ExtractionResult` objects or plain dicts.

```python
from docuflow.eval import EvalHarness

harness = EvalHarness()
harness.add_ground_truth(approved_result)
report = harness.compare_results(predicted=new_results)
```

### `EvalHarness`

Constructor:

```python
EvalHarness()
```

Methods:

```python
harness.add_ground_truth(result: ExtractionResult) -> None
harness.add_ground_truth_dict(document_id: str, values: dict[str, Any]) -> None
harness.compare_results(
    predicted: list[ExtractionResult],
    ground_truth: list[ExtractionResult] | None = None,
) -> EvalReport
await harness.evaluate(
    pipeline: object,
    schema: type[pydantic.BaseModel],
    files: list[str] | None = None,
) -> EvalReport
harness.evaluate_sync(
    pipeline: object,
    schema: type[pydantic.BaseModel],
    files: list[str] | None = None,
) -> EvalReport
```

Property:

```python
harness.ground_truth_count -> int
```

Comparison behavior:

- Results are matched to ground truth by `document_id`.
- Exact match uses normalized string equality.
- Fuzzy match accepts containment after normalization.
- Wrong values without evidence/source grounding count as hallucinated.
- Corrected predicted fields contribute to correction rate.

### `EvalReport`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `total_documents` | `int` | `0` | Number of ground-truth documents. |
| `field_scores` | `dict[str, FieldScore]` | `{}` | Per-field scores. |
| `overall_accuracy` | `float` | `0.0` | Exact plus fuzzy matches / total fields. |
| `hallucination_rate` | `float` | `0.0` | Hallucinated fields / total fields. |
| `correction_rate` | `float` | `0.0` | Corrected predicted fields / total fields. |
| `field_accuracy` | `dict[str, float]` | `{}` | Per-field accuracy. |

### `FieldScore`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `field_name` | `str` | Required | Field name. |
| `total` | `int` | `0` | Number of ground-truth examples. |
| `exact_match` | `int` | `0` | Exact normalized matches. |
| `fuzzy_match` | `int` | `0` | Fuzzy/containment matches. |
| `wrong` | `int` | `0` | Wrong but grounded values. |
| `missing` | `int` | `0` | Missing predicted values. |
| `hallucinated` | `int` | `0` | Wrong and not grounded/source-backed. |
| `accuracy` | `float` | `0.0` | `(exact_match + fuzzy_match) / total`. |

## CLI Batch And Routing Commands

### `extract-folder`

```bash
docuflow extract-folder ./invoices --schema invoice --output results.csv --parser smart
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--schema`, `-s` | Required | Template name or dotted Python path. |
| `--model`, `-m` | `"openai/gpt-4o"` | Extraction model. |
| `--parser`, `-p` | `"auto"` | Parser string. `"auto"` selects from the input type. |
| `--output`, `-o` | `None` | CSV output file. |
| `--pattern` | `"**/*.pdf"` | File glob pattern. |
| `--concurrency`, `-c` | `5` | Concurrent extractions. |

### `route`

```bash
docuflow route routes.yaml ./inbox --output results.csv
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `routes_path` | Required | Routes YAML path. |
| `input_path` | Required | File or folder. |
| `--output`, `-o` | `None` | CSV output path. |
| `--pattern` | `"**/*.pdf"` | Folder glob pattern. |
| `--concurrency`, `-c` | `5` | Concurrent documents. |
