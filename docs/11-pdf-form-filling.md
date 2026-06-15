# PDF Form Filling

DocuFlow can write trusted structured data into PDF forms. This is a write-back feature,
not extraction, so it returns a dedicated `FillingResult` instead of `ExtractionResult`.

Install the optional writer dependencies:

```bash
pip install docuflow[forms]
```

The `forms` extra installs `pypdf` for PDF writing, `reportlab` for static overlay
placements, and `pdfplumber` for opt-in blank-space detection.

## Public API

Imports:

```python
from docuflow import fill_pdf_form, fill_pdf_form_async
from docuflow.filling import FillingResult, FieldPlacement, FormField
```

### `fill_pdf_form()`

```python
fill_pdf_form(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    strategy: "auto" | "acroform" | "overlay" = "auto",
    match_by: "auto" | "name" | "alias" | "manual" | "label" | "llm" = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: "heuristic" | "llm" | "hybrid" = "heuristic",
    llm: Any = None,
    model: str = "openai/gpt-4o",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: "error" | "warn" | "ignore" = "warn",
    overflow: "error" | "shrink" | "wrap" = "shrink",
) -> FillingResult
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `path` | Required | Input PDF path. |
| `data` | Required | Pydantic model instance or mapping containing values to write. |
| `output_path` | `None` | Output PDF path. Defaults to `<input-stem>-filled.pdf`. |
| `strategy` | `"auto"` | `"auto"` inspects AcroForm fields first; `"acroform"` writes existing PDF fields; `"overlay"` writes text at explicit placements. |
| `match_by` | `"auto"` | AcroForm matching mode. `"auto"` tries aliases, then field names. `"manual"` relies on `field_map`. |
| `field_map` | `None` | Explicit model-field-to-PDF-field map, or overlay placements for static PDFs. |
| `formats` | `None` | Optional per-field format strings or callables. |
| `flatten` | `False` | Request flattened AcroForm output when the installed PDF backend supports it. Otherwise a warning is returned. |
| `detect_blank_spaces` | `False` | Opt-in static PDF blank detection. Only used for overlay filling when no `field_map` is supplied. Not active by default. |
| `blank_detection_mode` | `"heuristic"` | `"heuristic"` uses PDF geometry and labels; `"llm"` uses a vision LLM placement planner; `"hybrid"` uses heuristic placements first, then LLM for missing fields. |
| `llm` | `None` | Optional LLM adapter for LLM blank detection. If omitted, DocuFlow creates a `LiteLLMAdapter`. |
| `model` | `"openai/gpt-4o"` | LiteLLM model string for LLM blank detection. Requires `docuflow[llm]` unless `llm` is supplied. |
| `llm_kwargs` | `None` | Extra kwargs for the default `LiteLLMAdapter`. |
| `vision_dpi` | `DEFAULT_DPI` | Render DPI for page images sent to the vision LLM. |
| `min_detection_confidence` | `0.5` | Ignore LLM placements below this confidence. |
| `skip_none` | `True` | Skip fields whose value is `None`. |
| `unmatched` | `"warn"` | What to do when a model field cannot be mapped: add warning, error, or ignore. |
| `overflow` | `"shrink"` | Static overlay behavior when text is wider than the target box. |

### `fill_pdf_form_async()`

Async wrapper with the same parameters and return type:

```python
result = await fill_pdf_form_async("form.pdf", data=form_data)
```

## AcroForm Filling

Use this when the PDF already contains real form fields.

```python
from pydantic import BaseModel, Field
from docuflow import fill_pdf_form


class ClaimForm(BaseModel):
    claimant_name: str = Field(alias="claimant.name")
    policy_number: str
    accepted_terms: bool = False


data = ClaimForm(
    **{
        "claimant.name": "Mario Rossi",
        "policy_number": "POL-123456",
        "accepted_terms": True,
    }
)

result = fill_pdf_form(
    "blank-claim-form.pdf",
    data=data,
    output_path="filled-claim-form.pdf",
    strategy="acroform",
)
```

Matching priority in `match_by="auto"`:

1. Pydantic alias equals PDF field name.
2. Pydantic field name equals PDF field name.
3. Normalized alias or field name equals normalized PDF field name.
4. Explicit `field_map`.

You can also put the PDF field name in `json_schema_extra`:

```python
class ClaimForm(BaseModel):
    claimant_name: str = Field(
        json_schema_extra={"pdf_field": "topmostSubform[0].Page1[0].f1_1[0]"}
    )
```

Or pass a manual map:

```python
result = fill_pdf_form(
    "form.pdf",
    data=data,
    field_map={"claimant_name": "topmostSubform[0].Page1[0].f1_1[0]"},
)
```

Checkbox fields accept booleans. `True` writes the first discovered non-`Off` checkbox
option, or `"Yes"` when the option cannot be detected. `False` writes `"Off"`.

## Static PDF Overlay

Use overlay mode when the PDF has visual blanks but no real form fields. The default path
is explicit placements. Automatic blank-space detection exists, but it is intentionally
not active by default because static-form layout matching is heuristic.

Coordinates use DocuFlow's normal geometry convention: page-local, top-left origin, usually
PDF points.

```python
from docuflow import fill_pdf_form

result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    field_map={
        "claimant_name": {
            "page_number": 0,
            "bbox": {"x0": 72, "y0": 120, "x1": 260, "y1": 140},
            "font_size": 10,
        }
    },
)
```

### Opt-In Blank Detection

To let DocuFlow detect labeled blank lines automatically, set `detect_blank_spaces=True`.
The default mode uses PDF geometry and nearby label text. It does not call an LLM and it
should be reviewed before use.

```python
result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    detect_blank_spaces=True,  # off by default
)

result.fields["claimant_name"].method  # "auto_detected_blank"
result.warnings                        # includes detection summary
```

Detection currently handles labeled blank lines, simple boxes, and underscore blanks such
as `Name: __________`. For high-stakes forms, prefer explicit `field_map` placements.

### LLM-Assisted Blank Detection

For static forms where empty areas are not obvious lines or boxes, opt into the vision LLM
planner:

```python
result = fill_pdf_form(
    "static-claim-form.pdf",
    data={"claimant_name": "Mario Rossi", "address": "Via Roma 1"},
    output_path="static-claim-form-filled.pdf",
    strategy="overlay",
    detect_blank_spaces=True,
    blank_detection_mode="llm",   # "heuristic" | "llm" | "hybrid"
    model="openai/gpt-4o",
)

result.fields["claimant_name"].method  # "llm_detected_blank"
result.fields["claimant_name"].placement.confidence
result.fields["claimant_name"].placement.reason
```

The LLM is used only to produce a placement plan. It receives page images plus field names,
aliases, and descriptions; it does not receive the values to write and does not fill the PDF.

Coordinate contract:

- The LLM returns page-relative boxes: `x0`, `y0`, `x1`, `y1` from `0.0` to `1.0`.
- Origin is top-left, matching DocuFlow's document geometry convention.
- DocuFlow converts those relative boxes into `BoundingBox` values in page coordinates
  before writing.
- `FieldPlacement.bbox` and `FilledField.bbox` therefore use the same coordinate system as
  extraction evidence, search hits, OCR spans, and highlights.

Use `blank_detection_mode="hybrid"` to run heuristic detection first and ask the LLM only
for fields the heuristic detector did not map.

`field_map` values may be `FieldPlacement` objects or dictionaries containing:

| Field | Default | Description |
| --- | --- | --- |
| `page_number` | `0` | Zero-based page number. |
| `bbox` | Required | Target box using `x0`, `y0`, `x1`, `y1`. |
| `font_size` | `10.0` | Text size. |
| `font_name` | `"Helvetica"` | ReportLab font name. |
| `align` | `"left"` | `"left"`, `"center"`, or `"right"`. |
| `multiline` | `False` | Reserved for multi-line overlay behavior. |
| `source` | `""` | `"heuristic"` or `"llm"` when automatically detected. |
| `label_text` | `""` | Nearby label/context used for automatic detection. |
| `confidence` | `None` | Detector confidence, filled by LLM detection. |
| `reason` | `""` | Detector explanation. |
| `control_type` | `"text"` | Detector control type such as `"text"` or `"textarea"`. |

## `FillingResult`

```python
result.success
result.input_path
result.output_path
result.schema_name
result.strategy                 # "acroform" | "overlay"
result.data                     # values supplied by the user
result.fields["total"].value
result.fields["total"].formatted_value
result.fields["total"].target_name
result.fields["total"].page_number
result.fields["total"].bbox
result.fields["total"].method
result.pdf_fields               # discovered PDF fields for AcroForms
result.unmapped_model_fields
result.unmapped_pdf_fields
result.warnings
result.errors
result.trace_id

# Review state (see "Review & Approval" below)
result.committed                # True once the PDF has actually been written
result.needs_review             # set by review heuristics when review=True
result.review_status            # "pending" | "approved" | "rejected"
result.reviewed_by
result.reviewed_at
result.rejection_reason
result.review_reasons           # human-readable reasons the fill was flagged
result.corrections              # [FillCorrection(...)] audit log of reviewer edits
```

`FillingResult.fields` contains `FilledField` objects:

| Field | Description |
| --- | --- |
| `field_name` | Pydantic/mapping field name. |
| `value` | Original Python value. |
| `formatted_value` | Value written to the PDF. |
| `target_name` | PDF field name or overlay target name. |
| `page_number` | Page where the value was written, when known. |
| `bbox` | Target rectangle, when known. |
| `placement` | Static overlay placement, when used. |
| `method` | Mapping method such as `"exact_alias"`, `"exact_name"`, or `"manual_overlay"`. |
| `status` | `"filled"`, `"skipped"`, or `"failed"`. |
| `warnings` | Field-level warnings, such as font-size shrinkage. |

## Review & Approval

Because filling writes data *into* a file, any human review has to happen **before** the
PDF is saved. This is opt-in: pass `review=True` to **prepare** a fill without writing it.
The plan is built and review heuristics run, but `output_path` is not touched until you
approve and commit. With the default `review=False`, the PDF is written immediately, exactly
as before.

```python
from docuflow import fill_pdf_form, preview_fill, commit_fill

# 1. Prepare — nothing is written to output_path yet
result = fill_pdf_form("form.pdf", data, output_path="filled.pdf", review=True)
result.review_status      # "pending"
result.needs_review       # True when a heuristic flagged the fill
result.review_reasons     # why it was flagged
result.committed          # False

# 2. Show it — render each affected page with planned values overlaid (UI backend)
images = preview_fill(result, output_dir="./preview")   # -> list of PNG paths

# 3. Edit values and/or placements; originals are preserved, edits are logged
result.edit_field("recipient", value="Maria Bianchi", corrected_by="alice", reason="typo")
result.edit_field("recipient", bbox={"x0": 100, "y0": 200, "x1": 300, "y1": 220})

# 4. Decide, then commit
result.approve(approved_by="alice")     # or result.reject(rejected_by="alice", reason="...")
commit_fill(result)                     # writes filled.pdf; requires approval (or force=True)
result.committed          # True
```

### `result.edit_field(field_name, *, value=..., bbox=..., page_number=..., font_size=..., align=..., corrected_by="", reason="")`

Unified editor for a planned fill. Pass `value=` to change what is written; pass any of
`bbox` / `page_number` / `font_size` / `align` to change where/how it lands (overlay
strategy). The first edit to a field preserves its `original_value`/placement, and every
edit appends a `FillCorrection` to `result.corrections`. Raises if the result is already
committed or rejected.

### `result.approve(approved_by="")` / `result.reject(rejected_by="", reason="")`

Stamp the decision (`review_status`, `reviewed_by`, `reviewed_at`). Each guards against
deciding twice.

### `commit_fill(result, *, force=False)` / `commit_fill_async(...)`

Write an approved result to its `output_path`. Refuses a rejected result, and refuses a
pending one unless `force=True`. Idempotent guard: a result can only be committed once.

### `preview_fill(result, output_dir=".", *, dpi=150, format="png")` / `preview_fill_async(...)`

Render each affected page with the planned values drawn at their target boxes and save
images. Reviewer-edited or warned fields are highlighted in amber, clean placements in
green. This is the backend a review UI consumes — no PDF is written. Returns the saved
image paths.

### Persistence

`LocalDocumentStore` saves fills to `filling.json`:

```python
await store.save_filling_result(result)
ids = await store.get_pending_fills()              # review-flagged, still pending
result = await store.load_filling_result(doc_id)
```

`FillCorrection` records one reviewer edit: `field_name`, `old_value`, `new_value`,
`old_placement`, `new_placement`, `corrected_by`, `reason`, `timestamp`.

## Workflow Step

Manual pipelines can use `FillForm`:

```python
from docuflow.workflow import Pipeline, Ingest, FillForm

pipeline = Pipeline([
    Ingest(path="blank-form.pdf"),
    FillForm(data=data, output_path="filled-form.pdf"),
])

pipeline_result = pipeline.run_sync()
filling_result = pipeline_result.state.filling_result
```

`FillForm` accepts the same key options as `fill_pdf_form()`:

| Parameter | Default |
| --- | --- |
| `data` | `None` |
| `output_path` | `None` |
| `review` | `False` |
| `strategy` | `"auto"` |
| `match_by` | `"auto"` |
| `field_map` | `None` |
| `formats` | `None` |
| `flatten` | `False` |
| `detect_blank_spaces` | `False` |
| `blank_detection_mode` | `"heuristic"` |
| `llm` | `None` |
| `model` | `"gemini/gemini-2.5-flash"` |
| `llm_kwargs` | `None` |
| `vision_dpi` | `DEFAULT_DPI` |
| `min_detection_confidence` | `0.5` |
| `skip_none` | `True` |
| `unmatched` | `"warn"` |
| `overflow` | `"shrink"` |

## Current Limits

- AcroForm filling is deterministic and should be the default for real PDF forms.
- Static overlay defaults to explicit `field_map` placements.
- Automatic static blank detection is available only with `detect_blank_spaces=True`.
- LLM-assisted static blank detection requires `detect_blank_spaces=True` plus
  `blank_detection_mode="llm"` or `"hybrid"`.
- XFA-only forms are not guaranteed to work with the current writer backend.
- Signature fields are discovered but not signed.
