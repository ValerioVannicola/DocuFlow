# Extension Points, Tracing, And Errors

This file covers DocuFlow APIs used when extending or embedding the library:

- Custom LLM adapters.
- Custom OCR engines.
- Custom privacy providers.
- Custom strategies.
- Local ingestion helpers.
- Low-level PDF rendering.
- Traces and trace events.
- Exception classes.

## LLM Adapter Protocol

Use this protocol when you want to supply your own LLM client instead of `LiteLLMAdapter`.

Import:

```python
from docuflow.extraction.llm.base import LLMAdapter, LLMResponse
```

Protocol:

```python
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict],
        response_format: type[pydantic.BaseModel] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `messages` | Required | Chat-style messages. Content may include text or provider-specific multimodal payloads. |
| `response_format` | `None` | Pydantic model class or provider JSON response-format hint, depending on caller. |
| `temperature` | `0.0` | Sampling temperature. |

Return `LLMResponse`.

## `LLMResponse`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `content` | `str` | `""` | Model response text. Usually JSON for extraction/review calls. |
| `usage` | `dict` | `{}` | Token usage dict. Supported keys include `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`. |
| `model` | `str` | `""` | Model name returned by provider. |
| `raw_response` | `Any` | `None` | Provider raw response object. |

## `LiteLLMAdapter`

Import:

```python
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter
```

Constructor:

```python
LiteLLMAdapter(
    model: str = "openai/gpt-4o",
    api_key: str | None = None,
    max_retries: int = 3,
    prompt_caching: bool = False,
    suppress_debug_info: bool = True,
    **kwargs: Any,
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | `"openai/gpt-4o"` | LiteLLM model string. `provider:model` is translated to `provider/model`. |
| `api_key` | `None` | Explicit API key. If omitted, provider env vars are used. |
| `max_retries` | `3` | Number of retry attempts. |
| `prompt_caching` | `False` | For Anthropic models, marks the system message cacheable. |
| `suppress_debug_info` | `True` | Suppresses LiteLLM's feedback/debug-help banner on provider errors. Set to `False` to restore it. |
| `**kwargs` | `{}` | Extra kwargs passed to `litellm.acompletion()`. |

Method:

```python
await adapter.complete(
    messages: list[dict],
    response_format: type[pydantic.BaseModel] | None = None,
    temperature: float = 0.0,
) -> LLMResponse
```

Raises `SchemaExtractionError` after retries are exhausted.

## OCR Engine Protocol

Import:

```python
from docuflow.ocr.base import OCREngine, OCRResult, blocks_to_points
```

Protocol:

```python
class OCREngine(Protocol):
    async def ocr(self, image: PIL.Image.Image, language: str = "eng") -> OCRResult:
        ...
```

### `OCRResult`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `text` | `str` | `""` | Full OCR text. |
| `confidence` | `float` | `0.0` | Aggregate confidence. |
| `blocks` | `list[Block]` | `[]` | OCR blocks. |
| `language` | `str` | `"eng"` | OCR language. |
| `mean_word_confidence` | `float` | `0.0` | Mean confidence across words. |
| `low_confidence_word_ratio` | `float` | `0.0` | Fraction of low-confidence words. |
| `word_count` | `int` | `0` | Number of recognized words. |

### `blocks_to_points()`

```python
blocks_to_points(blocks: list[Block], dpi: int) -> list[Block]
```

Converts rendered-image pixel coordinates to PDF points using `72 / dpi`.

## Privacy Provider Protocols

Import:

```python
from docuflow.privacy.provider import PrivacyProvider, ImagePrivacyProvider
```

### `PrivacyProvider`

```python
async def adetect_text(
    text: str,
    entities: list[str] | None = None,
    language: str = "en",
    score_threshold: float = 0.35,
) -> list[PrivacyFinding]
```

```python
async def aanonymize_text(
    text: str,
    findings: list[PrivacyFinding],
    mode: AnonymizationMode,
    token_map: dict[str, str] | None = None,
) -> tuple[str, list[TokenMapping]]
```

```python
async def arestore_text(
    text: str,
    mappings: list[TokenMapping],
) -> str
```

### `ImagePrivacyProvider`

```python
async def aredact_image(
    image: PIL.Image.Image,
    findings: list[PrivacyFinding],
) -> PIL.Image.Image
```

Image privacy is an extension protocol for providers that can redact images.

## Strategy Protocol

Import:

```python
from docuflow.strategies import Strategy
```

Protocol:

```python
class Strategy(Protocol):
    async def execute(
        self,
        document: Document,
        schema: type[pydantic.BaseModel],
        **kwargs: object,
    ) -> ExtractionResult:
        ...
```

Use this to package a custom extraction strategy behind one `execute()` method.
The returned object should be the full `ExtractionResult` contract documented in
`06-results-and-data-models.md`, including field metadata, review state, and runtime metadata.

## Local Ingestion

Import:

```python
from docuflow.ingestion.local import ingest_file, ingest_file_sync, ingest_folder
```

### `ingest_file()`

```python
await ingest_file(path: str | pathlib.Path) -> Document
```

Behavior:

- Resolves the path.
- Raises `FileNotFoundError` if it is not a file.
- Detects MIME type.
- Computes SHA-256 file hash.
- Stores file size, path, file URI, and file name in `DocumentMetadata`.
- Returns a `Document` with status `"ingested"` and no parsed pages.

### `ingest_file_sync()`

```python
ingest_file_sync(path: str | pathlib.Path) -> Document
```

Sync wrapper around `ingest_file()`.

### `ingest_folder()`

```python
ingest_folder(
    path: str | pathlib.Path,
    pattern: str = "**/*.pdf",
) -> AsyncIterator[Document]
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `path` | Required | Folder path. Raises `NotADirectoryError` if missing. |
| `pattern` | `"**/*.pdf"` | Glob pattern. |

Yields ingested `Document` objects for matching files in sorted order.

## Low-Level PDF Rendering

Import:

```python
from docuflow.rendering.renderer import render_page, render_all_pages
```

### `render_page()`

```python
await render_page(
    file_path: str | pathlib.Path,
    page_number: int = 0,
    dpi: int = DEFAULT_DPI,
) -> PIL.Image.Image
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | PDF path. |
| `page_number` | `0` | Zero-based page index. |
| `dpi` | `DEFAULT_DPI` | Render DPI. |

Raises `ParsingError` when the PDF cannot be opened or page number is out of range.

### `render_all_pages()`

```python
await render_all_pages(
    file_path: str | pathlib.Path,
    dpi: int = DEFAULT_DPI,
) -> list[PIL.Image.Image]
```

Renders all pages. Rendering uses `pypdfium2`, so install `docuflow[pdf]`.

Implementation note: PDFium access is serialized with a lock because PDFium is not thread-safe.

## Tracing

Traces record workflow events, step durations, errors, and metadata.

Import:

```python
from docuflow.observability import Trace, TraceEvent, create_trace
```

### `TraceEvent`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `timestamp` | `datetime` | `datetime.now()` | Event time. |
| `event_type` | `str` | Required | Event type, such as `"ingest"` or `"error"`. |
| `step_name` | `str` | `""` | Workflow step name. |
| `duration_ms` | `float \| None` | `None` | Duration in milliseconds. |
| `metadata` | `dict` | `{}` | Extra event metadata. |

### `Trace`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `trace_id` | `str` | UUID | Trace id. |
| `document_id` | `str` | `""` | Document id. |
| `events` | `list[TraceEvent]` | `[]` | Events. |
| `started_at` | `datetime` | `datetime.now()` | Start time. |
| `completed_at` | `datetime \| None` | `None` | Completion time. |

Methods:

```python
trace.add_event(
    event_type: str,
    step_name: str = "",
    duration_ms: float | None = None,
    **metadata: object,
) -> None
```

```python
trace.complete() -> None
```

### `create_trace()`

```python
create_trace(document_id: str) -> Trace
```

Creates a trace initialized with a document id.

## Exceptions

Import:

```python
from docuflow.errors import (
    DocuflowError,
    UnsupportedFileTypeError,
    ParsingError,
    OCRError,
    OCRFailure,
    SchemaExtractionError,
    ValidationError,
    EvidenceNotFoundError,
    StorageError,
    WorkflowError,
    HumanReviewRequiredError,
    HumanReviewRequired,
    PrivacyError,
    AnonymizationError,
)
```

Exception hierarchy and purpose:

| Exception | Base | Purpose |
| --- | --- | --- |
| `DocuflowError` | `Exception` | Base class for DocuFlow-specific errors. |
| `UnsupportedFileTypeError` | `DocuflowError` | Unsupported input type. |
| `ParsingError` | `DocuflowError` | Parser/rendering/cloud OCR parse failures. |
| `OCRError` | `DocuflowError` | OCR failures. |
| `OCRFailure` | `OCRError` alias | Backward-compatible OCR error alias. |
| `SchemaExtractionError` | `DocuflowError` | LLM/schema extraction failures. |
| `ValidationError` | `DocuflowError` | Runtime validation exception, distinct from `docuflow.validation.ValidationError` model. |
| `EvidenceNotFoundError` | `DocuflowError` | Evidence lookup failures. |
| `StorageError` | `DocuflowError` | Storage failures. |
| `WorkflowError` | `DocuflowError` | Workflow-level failure wrapper. |
| `HumanReviewRequiredError` | `DocuflowError` | Raised by integrations that enforce manual review. |
| `HumanReviewRequired` | `HumanReviewRequiredError` alias | Backward-compatible alias. |
| `PrivacyError` | `DocuflowError` | Privacy base error. |
| `AnonymizationError` | `PrivacyError` | Anonymization or restoration failure. |

### Exception Attributes

`docuflow.errors.ValidationError`:

```python
ValidationError(
    message: str,
    field_name: str | None = None,
    rule_name: str | None = None,
)
```

Attributes:

- `field_name`
- `rule_name`

`WorkflowError`:

```python
WorkflowError(message: str, result: object | None = None)
```

Attributes:

- `result`: partial workflow result/state object when available.

`HumanReviewRequiredError`:

```python
HumanReviewRequiredError(
    message: str,
    document_id: str | None = None,
    reason: str | None = None,
)
```

Attributes:

- `document_id`
- `reason`

## Naming Collision Note

There are two `ValidationError` names:

- `docuflow.validation.ValidationError` is a Pydantic model returned by validators.
- `docuflow.errors.ValidationError` is an exception class.

Prefer explicit imports when using both:

```python
from docuflow.validation import ValidationError as ValidationIssue
from docuflow.errors import ValidationError as ValidationException
```
