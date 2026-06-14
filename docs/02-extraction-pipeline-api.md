# Extraction Pipeline API

This file documents the high-level extraction APIs users call most often:

- `docuflow.extract()`
- `docuflow.extract_async()`
- `docuflow.DocumentPipeline`
- `DocumentPipeline.run()`
- `DocumentPipeline.run_sync()`

Use these APIs when you want DocuFlow to assemble ingestion, parsing, extraction, validation,
review, optional verification, and storage for you.

## One-Liner Extraction

```python
from docuflow import extract

result = extract("invoice.pdf", schema=Invoice, model="openai/gpt-4o")
```

### `extract()`

Synchronous import:

```python
from docuflow import extract
```

Actual implementation: `docuflow.api.extract_sync()`.

Signature:

```python
extract(
    path: str,
    schema: type[pydantic.BaseModel],
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult
```

Parameters:

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `path` | `str` | Required | Path to the document file. Usually a PDF, scan, or image-like document supported by the chosen parser. |
| `schema` | `type[BaseModel]` | Required | Pydantic schema class that defines fields to extract. |
| `model` | `str` | `"openai/gpt-4o"` | LiteLLM model string. `provider/model` and `provider:model` forms are accepted by the LiteLLM adapter. |
| `parser` | `str` | `"pdfplumber"` | Parser name. See parser options below. |
| `storage` | `str \| None` | `None` | Storage backend. `None` disables storage; `"local"` stores under `./.docuflow_store`. |
| `privacy` | `Any` | `None` | Usually a `PrivacyPolicy`. When set, parsed text is anonymized before extraction. |
| `**kwargs` | `Any` | `{}` | Forwarded directly to `DocumentPipeline`. Use for `extraction_type`, `extraction_mode`, `n_instances`, `review_rules`, etc. |

Returns: `ExtractionResult`.

### `extract_async()`

Async import:

```python
from docuflow import extract_async
```

Actual implementation: `docuflow.api.extract()`.

Signature:

```python
await extract_async(
    path: str,
    schema: type[pydantic.BaseModel],
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
    storage: str | None = None,
    privacy: Any = None,
    **kwargs: Any,
) -> ExtractionResult
```

The parameter semantics are identical to sync `extract()`.

## `DocumentPipeline`

`DocumentPipeline` is the reusable, configurable high-level API.

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser="smart",
    model="openai/gpt-4o",
    extraction_type="auto",
    extraction_mode="multi",
    n_instances=3,
)

result = pipeline.run_sync("invoice.pdf", schema=Invoice)
```

Constructor signature:

```python
DocumentPipeline(
    parser: Any | str | dict | None = "pdfplumber",
    ocr: Any | str | None = None,
    model: str = "openai/gpt-4o",
    storage: Any | str | dict | None = None,
    validators: list | None = None,
    review_rules: list | None = None,
    privacy: Any = None,
    extraction_mode: str = "single",
    extraction_type: str = "text",
    n_instances: int = 5,
    temperatures: list[float] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    context: str | None = None,
    scoring: str = "qualitative",
    escalation: dict | None = None,
    verification: dict | None = None,
    schema_shards: int | None = None,
    llm_kwargs: dict | None = None,
)
```

### Constructor Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `parser` | `"pdfplumber"` | Parser selector, parser config dict, parser object, `None`, or `"none"`. `None`/`"none"` is required for direct `vision` and `hybrid` extraction. |
| `ocr` | `None` | Reserved/accepted for compatibility. The current high-level pipeline resolves OCR through parser choices. |
| `model` | `"openai/gpt-4o"` | LiteLLM model string used by the default `LiteLLMAdapter`. |
| `storage` | `None` | Storage backend selector/config/object. See storage options below. |
| `validators` | `None` | List of validator objects, for example `RequiredFields(["total"])`. |
| `review_rules` | `None` | List of review rule objects, for example `OverallConfidenceBelow(0.7)`. |
| `privacy` | `None` | Privacy policy object. In text paths, anonymizes text before LLM extraction. Cannot be used with `vision` or `hybrid`. |
| `extraction_mode` | `"single"` | `"single"` or `"multi"`. |
| `extraction_type` | `"text"` | `"text"`, `"vision"`, `"hybrid"`, or `"auto"`. |
| `n_instances` | `5` | Number of parallel extraction candidates in multi mode. Also used by hybrid/auto where applicable. |
| `temperatures` | `None` | Optional list of temperatures for multi-instance candidates. If omitted, engines choose their defaults. |
| `vision_dpi` | `DEFAULT_DPI` | DPI for rendering PDF pages when using vision, hybrid, auto escalation, or field verification. |
| `context` | `None` | Domain instructions appended to extraction prompts, such as policy-number formats or business rules. |
| `scoring` | `"qualitative"` | `"qualitative"` or `"quantitative"` trust scoring. |
| `escalation` | `None` | Dict configuring auto-mode vision escalation. |
| `verification` | `None` | Dict enabling zoom-and-verify for weak fields. |
| `schema_shards` | `None` | Number of text-only schema shards for wide schemas. |
| `llm_kwargs` | `None` | Extra options passed to `LiteLLMAdapter`, including `api_key`, `max_retries`, `prompt_caching`, and provider-specific LiteLLM kwargs. |

### Parser Options

String values:

| Value | Behavior | Install extra |
| --- | --- | --- |
| `"pdfplumber"` | Native PDF text layer extraction. Fast, no OCR confidence. | `docuflow[pdf]` |
| `"tesseract"` | Render pages and run local Tesseract OCR. | `docuflow[ocr,pdf]` plus system `tesseract` |
| `"docling"` | Docling layout parser with first-class tables. | `docuflow[docling]` |
| `"smart"` | Native PDF extraction first, OCR only pages that need it. | `docuflow[pdf,ocr]` plus system `tesseract` |
| `"azure-di"` | Azure Document Intelligence OCR. | `docuflow[azure]` |
| `"textract"` | AWS Textract OCR. Renders pages locally, no S3 required. | `docuflow[aws,pdf]` |
| `"google-docai"` | Google Document AI OCR. | `docuflow[gcp]` |
| `"none"` or `None` | No parser. Required for direct `vision` and `hybrid`. | `docuflow[pdf,llm]` |

Parser config dict values:

```python
DocumentPipeline(parser={"type": "tesseract", "languages": ["eng"], "dpi": 250})
```

Supported parser dict keys:

| `type` | Extra keys |
| --- | --- |
| `"pdfplumber"` | None. |
| `"tesseract"` | `languages: list[str]`, `dpi: int`, `preprocess: list[str]`. |
| `"docling"` | None. |
| `"smart"` | `languages: list[str]`, `dpi: int`, `min_text_length: int`. |
| `"azure-di"` | `endpoint: str`, `key: str`, `model: str`. |
| `"textract"` | `region: str`, `dpi: int`. |
| `"google-docai"` | `project: str`, `location: str`, `processor_id: str`. |

You may also pass a parser object implementing:

```python
async def parse(document: Document) -> Document
```

### Extraction Types

| `extraction_type` | Pipeline shape | Parser requirement | Use when |
| --- | --- | --- | --- |
| `"text"` | Ingest -> Parse -> Extract -> Validate -> Verify? -> Review -> Store? | Parser required, defaults to `pdfplumber`. | Normal text-layer or OCR-backed extraction. |
| `"vision"` | Ingest -> ExtractVision -> Validate -> Review -> Store? | `parser=None` or `"none"`. | A vision-capable LLM should read rendered page images directly. |
| `"hybrid"` | Ingest -> ExtractHybrid -> Validate -> Review -> Store? | `parser=None` or `"none"`. | Vision and text agents should run together and a decider should select values. |
| `"auto"` | Ingest -> Parse -> ExtractAuto -> Validate -> Verify? -> Review -> Store? | Usually `parser="smart"`. | Start with text/OCR; escalate to vision if OCR quality is poor. |

Important constraints:

- `vision` and `hybrid` raise `ValueError` if `parser` is not `None` or `"none"`.
- `vision` and `hybrid` raise `ValueError` if `privacy` is configured because raw page images bypass text anonymization.
- `auto` suppresses vision escalation when `privacy` is configured.

### Extraction Modes

| `extraction_mode` | LLM calls | Behavior |
| --- | --- | --- |
| `"single"` | 1 main call | One extraction pass. No consensus score. |
| `"multi"` | N candidates plus optional decider | Multiple candidates run in parallel. If all candidates agree, the decider can be skipped; otherwise a decider chooses final values. |

Related parameters:

- `n_instances`: number of candidate calls in multi mode.
- `temperatures`: optional list of floats. Use to control candidate diversity.
- `scoring`: affects trust score calculation, not the schema.

### Scoring

`scoring="qualitative"` uses binary source verification/auto-accept behavior.

`scoring="quantitative"` asks scoring logic to express confidence/trust as a percentage-like score where supported.

In both modes, DocuFlow does not trust LLM self-reported confidence. It combines agreement, source verification, validation, evidence, and OCR signals when available.

### LLM Options

By default, `DocumentPipeline` builds:

```python
LiteLLMAdapter(model=model, **llm_kwargs)
```

Supported adapter constructor parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | `"openai/gpt-4o"` | LiteLLM model string. `openai:gpt-4o` is translated to `openai/gpt-4o`. |
| `api_key` | `None` | Optional explicit API key. Otherwise provider env vars are used. |
| `max_retries` | `3` | Retry count for failed LLM calls. |
| `prompt_caching` | `False` | When true and model starts with `anthropic`, marks the system prompt cacheable. |
| `suppress_debug_info` | `True` | Suppresses LiteLLM's feedback/debug-help banner on provider errors. Set to `False` when debugging LiteLLM itself. |
| `**kwargs` | `{}` | Passed through to `litellm.acompletion()`. |

Example:

```python
pipeline = DocumentPipeline(
    model="anthropic/claude-sonnet-4-6",
    llm_kwargs={
        "max_retries": 5,
        "prompt_caching": True,
        "suppress_debug_info": True,
        "timeout": 60,
    },
)
```

### Auto Escalation

Auto mode uses `extraction_type="auto"` and evaluates OCR quality after parsing.

```python
pipeline = DocumentPipeline(
    parser="smart",
    extraction_type="auto",
    escalation={
        "min_ocr_score": 0.6,
        "max_low_confidence_ratio": 0.4,
        "escalate_to": "vision",
    },
)
```

Supported keys:

| Key | Type | Meaning |
| --- | --- | --- |
| `min_ocr_score` | `float` | Escalate when document OCR score is below this value. |
| `max_low_confidence_ratio` | `float` | Escalate when too many OCR words fall below the low-confidence threshold. |
| `escalate_to` | `"vision"` or `"hybrid"` | Engine to use for re-reading when escalation is triggered. |

Result fields:

```python
result.escalated
result.escalation_reason
```

Privacy note: if `privacy` is configured, auto mode will not escalate to vision.

### Zoom-And-Verify

Verification re-reads weak fields individually from high-DPI crops.

```python
pipeline = DocumentPipeline(
    verification={
        "trigger_consensus_below": 0.7,
        "trigger_ocr_below": 0.6,
        "include_unmatched": True,
        "max_fields": 5,
        "dpi": 300,
        "apply_corrections": True,
    },
)
```

Supported keys:

| Key | Type | Meaning |
| --- | --- | --- |
| `trigger_consensus_below` | `float` | Verify fields whose consensus ratio is below this value. |
| `trigger_ocr_below` | `float` | Verify fields whose matched OCR confidence is below this value. |
| `include_unmatched` | `bool` | Verify fields whose value could not be matched back to OCR text. |
| `max_fields` | `int` | Maximum number of fields to verify per document. |
| `dpi` | `int` | DPI for high-resolution crop rendering. |
| `apply_corrections` | `bool` | Apply schema-valid corrected values returned by the vision LLM. |

Per-field result:

```python
field.verification.verified
field.verification.agrees
field.verification.changed
field.verification.original_value
field.verification.verified_value
field.verification.reason
```

### Schema Sharding

Wide schemas can be split into parallel partial extractions and merged:

```python
pipeline = DocumentPipeline(schema_shards=3)
```

Notes:

- Intended for text extraction.
- Use when a schema has many fields and one prompt becomes too large or unreliable.
- Final result is still one `ExtractionResult`.

### Storage Options

```python
DocumentPipeline(storage=None)
DocumentPipeline(storage="local")
DocumentPipeline(storage={"type": "local", "path": "./output"})
DocumentPipeline(storage=LocalDocumentStore("./output"))
```

Supported built-in storage values:

| Value | Behavior |
| --- | --- |
| `None` | Do not store documents, results, or traces. |
| `"local"` | Store under `./.docuflow_store`. |
| `{"type": "local", "path": "..."}` | Store under the given directory. |

You may pass a custom object implementing the storage protocol documented in
`07-validation-review-privacy-and-storage.md`.

### Validation And Review Options

```python
from docuflow.validation import RequiredFields, EvidenceRequired
from docuflow.review import OverallConfidenceBelow, FieldMissing

pipeline = DocumentPipeline(
    validators=[
        RequiredFields(["supplier_name", "total"]),
        EvidenceRequired(["total"]),
    ],
    review_rules=[
        OverallConfidenceBelow(0.7),
        FieldMissing(["total"]),
    ],
)
```

Validation runs before review. Review rules set:

```python
result.needs_review
result.review_reasons
```

### `DocumentPipeline.run()`

Async signature:

```python
await pipeline.run(
    path: str,
    schema: type[pydantic.BaseModel],
    **kwargs: Any,
) -> ExtractionResult
```

Parameters:

| Parameter | Description |
| --- | --- |
| `path` | File path to ingest and process. |
| `schema` | Pydantic schema class. |
| `**kwargs` | Reserved for future pipeline metadata; current high-level implementation mainly uses constructor settings. |

### `DocumentPipeline.run_sync()`

Sync signature:

```python
pipeline.run_sync(
    path: str,
    schema: type[pydantic.BaseModel],
    **kwargs: Any,
) -> ExtractionResult
```

Same parameters and return type as async `run()`.

The returned `ExtractionResult` is the full final document payload, not just the flat
`data` dict. It includes:

- `document_id`, `schema_name`, `data`, `fields`
- `confidence`, `ocr`, `usage`
- `escalated`, `escalation_reason`
- `needs_review`, `review_status`, `reviewed_by`, `reviewed_at`, `rejection_reason`
- `review_reasons`, `review_verdicts`, `corrections`, `validation_errors`
- `trace_id`, `model_name`, `parser_name`, `raw_text`

For the per-field contract, trust model, provenance, and serialization details, see
`06-results-and-data-models.md`.

## Practical Recipes

Native PDF:

```python
pipeline = DocumentPipeline(parser="pdfplumber", model="openai/gpt-4o")
result = pipeline.run_sync("invoice.pdf", Invoice)
```

Scanned PDF:

```python
pipeline = DocumentPipeline(
    parser={"type": "tesseract", "languages": ["eng"], "dpi": 300},
    model="openai/gpt-4o",
)
```

Mixed native/scanned PDFs:

```python
pipeline = DocumentPipeline(parser="smart", model="openai/gpt-4o")
```

Direct vision:

```python
pipeline = DocumentPipeline(
    parser=None,
    extraction_type="vision",
    model="openai/gpt-4o",
)
```

Multi-agent extraction with review:

```python
pipeline = DocumentPipeline(
    parser="smart",
    extraction_mode="multi",
    n_instances=3,
    review_rules=[OverallConfidenceBelow(0.8)],
)
```

Privacy-safe text extraction:

```python
from docuflow import PrivacyPolicy
from docuflow.privacy import PresidioProvider

pipeline = DocumentPipeline(
    parser="tesseract",
    privacy=PrivacyPolicy(provider=PresidioProvider(), mode="pseudonymize"),
)
```
