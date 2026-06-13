# Validation, Review, Privacy, And Storage

This file documents the public APIs for post-extraction validation, human/LLM review,
privacy/anonymization, and local persistence.

## Validation

Validation runs after extraction and before review. Validators update:

```python
result.validation_errors
result.fields[field_name].validation_status
result.fields[field_name].errors
```

Use validators through `DocumentPipeline`:

```python
from docuflow import DocumentPipeline
from docuflow.validation import RequiredFields, EvidenceRequired

pipeline = DocumentPipeline(
    validators=[
        RequiredFields(["supplier_name", "total"]),
        EvidenceRequired(["total"]),
    ],
)
```

Or manually:

```python
from docuflow.validation import validate

result = validate(result, validators)
```

## Validator Protocol

Import:

```python
from docuflow.validation import Validator
```

Protocol:

```python
def validate(self, result: object) -> list[ValidationError]
```

Custom validators can implement this method.

## `ValidationError`

```python
from docuflow.validation import ValidationError
```

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `field_name` | `str` | Required | Field that failed validation. |
| `rule_name` | `str` | Required | Validator/rule identifier. |
| `message` | `str` | Required | Human-readable validation message. |
| `severity` | `str` | `"error"` | `"error"` or `"warning"`. |

## Built-In Validators

### `RequiredFields`

```python
from docuflow.validation import RequiredFields

RequiredFields(fields: list[str])
```

Parameters:

| Parameter | Description |
| --- | --- |
| `fields` | Field names that must exist in `result.fields` and have non-`None` values. |

### `EvidenceRequired`

```python
from docuflow.validation import EvidenceRequired

EvidenceRequired(fields: list[str] | None = None)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `fields` | `None` | Field names that must have evidence. If `None`, checks all result fields. |

Only fields with non-`None` values are checked.

### `TypeValidation`

```python
from docuflow.validation import TypeValidation

TypeValidation()
```

Current behavior:

- Flags empty string values as warnings.
- Does not perform full Pydantic re-validation of result values.

### `CustomRule`

```python
from docuflow.validation import CustomRule

CustomRule(
    name: str,
    fn: Callable[[ExtractionResult], list[ValidationError]],
)
```

Parameters:

| Parameter | Description |
| --- | --- |
| `name` | Rule name stored on the custom rule object. |
| `fn` | Function that receives `ExtractionResult` and returns validation errors. |

Example:

```python
from docuflow.validation import CustomRule, ValidationError

def positive_total(result):
    total = result.fields.get("total")
    if total and total.value is not None and total.value < 0:
        return [ValidationError(
            field_name="total",
            rule_name="positive_total",
            message="Total cannot be negative",
        )]
    return []

validator = CustomRule("positive_total", positive_total)
```

## `validate()`

```python
from docuflow.validation import validate

validate(
    result: ExtractionResult,
    validators: list[Validator],
) -> ExtractionResult
```

Runs all validators and returns the same updated result object.

Validation status behavior:

- A field with any `severity="error"` gets `validation_status = "error"`.
- A field with warnings but no errors gets `validation_status = "warning"`.
- Other fields get `validation_status = "valid"`.

## Review

Review rules run after validation. They decide whether a result needs human review.

```python
from docuflow.review import OverallConfidenceBelow, FieldMissing

pipeline = DocumentPipeline(
    review_rules=[
        OverallConfidenceBelow(0.7),
        FieldMissing(["total", "invoice_number"]),
    ],
)
```

Review updates:

```python
result.needs_review
result.review_reasons
result.review_verdicts
```

## Review Rule Protocol

```python
from docuflow.review import ReviewRule

def check(self, result: ExtractionResult) -> str | None
```

Return a reason string to mark the document for review, or `None` to pass.

## Built-In Review Rules

### `OverallConfidenceBelow`

```python
OverallConfidenceBelow(threshold: float = 0.7)
```

Flags review when `result.confidence < threshold`.

### `FieldConfidenceBelow`

```python
FieldConfidenceBelow(fields: dict[str, float])
```

Parameters:

| Parameter | Description |
| --- | --- |
| `fields` | Mapping of field name to minimum confidence threshold. |

Flags any named field whose `field.confidence` is below its threshold.

### `AnyFieldConfidenceBelow`

```python
AnyFieldConfidenceBelow(threshold: float = 0.6)
```

Flags the first field with confidence below the shared threshold.

### `HasValidationErrors`

```python
HasValidationErrors()
```

Flags review when `len(result.validation_errors) > 0`.

### `FieldMissing`

```python
FieldMissing(fields: list[str])
```

Flags review when any listed field is absent or has `value is None`.

### `NoEvidence`

```python
NoEvidence(fields: list[str] | None = None)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `fields` | `None` | Fields to check. `None` checks all fields. |

Only non-`None` field values are checked.

## LLM Reviewer

`LLMReviewer` runs an LLM prompt against the extraction result, field evidence, and original
document text.

```python
from docuflow.review import LLMReviewer
from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

auditor = LLMReviewer(
    name="financial_auditor",
    prompt="Check if totals and line items are mathematically consistent.",
    llm=LiteLLMAdapter(model="openai/gpt-4o"),
)
```

Constructor:

```python
LLMReviewer(
    name: str,
    prompt: str,
    llm: LLMAdapter,
)
```

Parameters:

| Parameter | Description |
| --- | --- |
| `name` | Reviewer name used in verdicts and review reasons. |
| `prompt` | Review instruction. |
| `llm` | LLM adapter implementing `complete()`. |

Methods:

```python
await reviewer.acheck(
    result: ExtractionResult,
    document_text: str = "",
) -> ReviewVerdict
```

```python
reviewer.check(result: ExtractionResult) -> str | None
```

`check()` is a no-op for protocol compatibility. The workflow `Review` step detects `acheck()`
and runs LLM reviewers asynchronously.

LLM reviewer verdicts:

- `"Approved"` means no review reason is added.
- Any other verdict becomes `"Not Approved"` and adds the reviewer reasoning to `review_reasons`.
- Reviewer token usage is merged into `result.usage`.

## Human Review Methods

On `ExtractionResult`:

```python
result.approve(approved_by="alice")
result.reject(rejected_by="alice", reason="wrong document")
result.correct_field("total", 1235.0, corrected_by="alice", reason="OCR error")
```

See `results-and-data-models.md` for the exact result fields modified by these methods.

## Privacy Policy

Privacy anonymizes text before it is sent to the LLM in text extraction paths.

```python
from docuflow import PrivacyPolicy
from docuflow.privacy import PresidioProvider

policy = PrivacyPolicy(
    provider=PresidioProvider(),
    mode="pseudonymize",
    reversible=True,
    fail_closed=True,
)
```

### `PrivacyPolicy`

Import:

```python
from docuflow import PrivacyPolicy
from docuflow.privacy import PrivacyPolicy
```

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `anonymize_before_llm` | `bool` | `True` | Policy flag indicating anonymization should happen before LLM calls. |
| `mode` | `AnonymizationMode` | `PSEUDONYMIZE` | `"redact"`, `"mask"`, `"pseudonymize"`, or `"hash"`. |
| `reversible` | `bool` | `True` | Whether mappings can restore original values. Requires `mode="pseudonymize"`. |
| `provider` | `Any` | `None` | Privacy provider, usually `PresidioProvider()`. |
| `entities` | `list[str]` | Common PII entities | Entity types to detect. |
| `fail_closed` | `bool` | `True` | If true, anonymization failure fails the workflow. |
| `score_threshold` | `float` | `0.35` | Minimum PII detection score. |
| `log_scrubbing` | `bool` | `True` | Policy flag for scrubbed logging. |
| `mapping_store` | `Any` | `None` | Mapping store for reversible pseudonymization. |

Default entities:

```python
[
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "LOCATION",
    "DATE_TIME",
]
```

Validation rule:

- `reversible=True` requires `mode="pseudonymize"`.

Vision/hybrid constraint:

- `DocumentPipeline(extraction_type="vision" | "hybrid", privacy=...)` raises `ValueError`.
- Auto mode suppresses vision escalation when privacy is configured.

## Privacy Modes

### `AnonymizationMode`

Import:

```python
from docuflow.privacy import AnonymizationMode
```

Enum values:

| Value | Behavior |
| --- | --- |
| `"redact"` | Replace detected text with `[REDACTED]`. |
| `"mask"` | Keep first character and replace the rest with `*`. |
| `"pseudonymize"` | Replace values with stable scoped tokens such as `PERSON_001`. |
| `"hash"` | Replace values with first 16 chars of SHA-256 hash. |

## Presidio Provider

Import:

```python
from docuflow.privacy import PresidioProvider
```

Constructor:

```python
PresidioProvider(language: str = "en", model: str | None = None)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `language` | `"en"` | Presidio analyzer language. |
| `model` | `None` | Reserved for model selection; the provider initializes Presidio's analyzer/anonymizer. |

Methods:

```python
await provider.adetect_text(
    text: str,
    entities: list[str] | None = None,
    language: str = "en",
    score_threshold: float = 0.35,
) -> list[PrivacyFinding]
```

```python
await provider.aanonymize_text(
    text: str,
    findings: list[PrivacyFinding],
    mode: AnonymizationMode,
    token_map: dict[str, str] | None = None,
) -> tuple[str, list[TokenMapping]]
```

```python
await provider.arestore_text(
    text: str,
    mappings: list[TokenMapping],
) -> str
```

Requires `docuflow[privacy]`.

## Anonymizer

Import:

```python
from docuflow.privacy import Anonymizer
```

Constructor:

```python
Anonymizer(policy: PrivacyPolicy)
```

Methods:

```python
await anonymizer.anonymize_text(
    text: str,
    scope_id: str | None = None,
) -> AnonymizedText
```

```python
await anonymizer.anonymize_document(
    document: Any,
    scope_id: str | None = None,
) -> AnonymizationResult
```

```python
await anonymizer.restore_text(text: str, mapping_id: str) -> str
await anonymizer.restore_result(result: Any, mapping_id: str) -> Any
```

Parameters:

| Parameter | Description |
| --- | --- |
| `scope_id` | Token scope for stable pseudonyms. Defaults to a UUID for text or `document.id` for documents. |
| `mapping_id` | Mapping id returned by anonymization when a mapping store is configured. |

## Privacy Data Models

### `PrivacyFinding`

| Field | Type | Description |
| --- | --- | --- |
| `entity_type` | `str` | Entity type such as `PERSON`. |
| `start` | `int` | Start offset. |
| `end` | `int` | End offset. |
| `text` | `str` | Original detected text. |
| `score` | `float` | Detection score. |
| `page_number` | `int \| None` | Page number when available. |
| `bbox` | `BoundingBox \| None` | Source bbox when available. |

### `TokenMapping`

| Field | Type | Description |
| --- | --- | --- |
| `token` | `str` | Replacement token. |
| `original` | `str` | Original text. |
| `entity_type` | `str` | Entity type. |

### `AnonymizedText`

| Field | Type | Description |
| --- | --- | --- |
| `text` | `str` | Anonymized text. |
| `mapping_id` | `str` | Mapping id. |
| `findings` | `list[PrivacyFinding]` | Detected findings. |
| `mappings` | `list[TokenMapping]` | Token mappings for this text. |

### `AnonymizationResult`

| Field | Type | Description |
| --- | --- | --- |
| `document_id` | `str` | Document id. |
| `mapping_id` | `str` | Mapping id. |
| `anonymized_text` | `str` | Full anonymized document text. |
| `findings` | `list[PrivacyFinding]` | All findings. |
| `token_mappings` | `list[TokenMapping]` | All mappings. |
| `mode` | `str` | Applied mode. |
| `page_results` | `list[AnonymizedText]` | Per-page anonymization results. |
| `risk_score` | `float` | Calculated PII risk score, 0-1. |

## Mapping Stores

### `MappingStore` Protocol

```python
async def save_mapping(mapping_id: str, mappings: list[TokenMapping]) -> None
async def load_mapping(mapping_id: str) -> list[TokenMapping] | None
async def delete_mapping(mapping_id: str) -> None
```

### `LocalMappingStore`

Import:

```python
from docuflow.privacy.mapping_store import LocalMappingStore
```

Constructor:

```python
LocalMappingStore(base_path: str = "./.docuflow_mappings")
```

Stores one JSON file per mapping id under `base_path`.

## Storage

Storage saves original documents, parsed document JSON, extraction JSON, and traces.

Use through `DocumentPipeline`:

```python
pipeline = DocumentPipeline(storage="local")
```

Or directly:

```python
from docuflow.storage.local import LocalDocumentStore

store = LocalDocumentStore("./output")
await store.save_result(result)
```

## Storage Protocol

Import:

```python
from docuflow.storage.base import Storage
```

Protocol:

```python
async def save_document(document: Document) -> str
async def save_result(result: ExtractionResult) -> str
async def save_trace(trace: Trace) -> str
async def load_result(document_id: str) -> ExtractionResult | None
async def load_document(document_id: str) -> Document | None
async def list_documents() -> list[str]
async def get_pending_reviews() -> list[str]
async def get_by_status(status: str) -> list[str]
```

Pass any object with this interface as `DocumentPipeline(storage=...)` or `Store(storage=...)`.

## `LocalDocumentStore`

Import:

```python
from docuflow.storage.local import LocalDocumentStore
```

Constructor:

```python
LocalDocumentStore(base_path: str = "./.docuflow_store")
```

Directory layout:

```text
base_path/
  <document_id>/
    original.pdf
    document.json
    extraction.json
    trace.json
```

Methods:

```python
await store.save_document(document: Document) -> str
await store.save_result(result: ExtractionResult) -> str
await store.save_trace(trace: Trace) -> str
await store.load_result(document_id: str) -> ExtractionResult | None
await store.load_document(document_id: str) -> Document | None
await store.list_documents() -> list[str]
await store.get_pending_reviews() -> list[str]
await store.get_by_status(status: str) -> list[str]
```

Status values for `get_by_status()`:

| Status | Meaning |
| --- | --- |
| `"pending_review"` | `result.needs_review` and `review_status == "pending"`. |
| `"approved"` | `review_status == "approved"`. |
| `"rejected"` | `review_status == "rejected"`. |
| `"pending"` | `review_status == "pending"` and `needs_review == False`. |

`get_pending_reviews()` is equivalent to `get_by_status("pending_review")`.
