# Document Splitting

DocuFlow can split a document into named logical sections by asking an LLM to assign each
page to one or more categories you define. This is useful for preprocessing long documents
before targeted extraction (e.g. "extract only the exhibits section") or for routing pages
to different downstream handlers.

Requires the `llm` and `pdf` extras:

```bash
pip install docuflow[pdf,llm]
```

## Public API

```python
from docuflow import split_document, split_document_async
from docuflow.splitting import DocumentSection, SplitResult
```

## Defining sections

Sections are defined via a **Pydantic model class** whose field names become section
identifiers and whose `Field(description=...)` values describe what belongs there:

```python
from pydantic import BaseModel, Field
from docuflow import split_document

class ContractSections(BaseModel):
    contract_body: str = Field(description="Main contract terms and conditions")
    exhibits: str = Field(description="Attached exhibits and appendices")
    signature_page: str = Field(description="Pages containing signature blocks")

result = split_document("contract.pdf", ContractSections)
print(result.page_map)
# → {"contract_body": [0, 1, 2], "exhibits": [3, 4], "signature_page": [5]}
```

Alternatively, pass a **list of `DocumentSection` objects** for a more explicit approach:

```python
from docuflow.splitting import DocumentSection

result = split_document("contract.pdf", [
    DocumentSection(name="contract_body", description="Main contract terms"),
    DocumentSection(name="exhibits",      description="Attached exhibits"),
])
```

Both approaches produce identical results; the Pydantic schema is recommended for
code-defined pipelines and YAML workflows, and the list form is convenient for dynamic
section names.

## `split_document()`

```python
split_document(
    path: str,
    schema: type[BaseModel] | list[DocumentSection],
    *,
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: list[int] | None = None,
    llm: Any = None,
    llm_kwargs: Mapping[str, Any] | None = None,
) -> SplitResult
```

`split_document_async` is the async version; `split_document` is the sync wrapper.

### Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `path` | required | Path to the PDF document. |
| `schema` | required | Section definitions — Pydantic class or `list[DocumentSection]`. |
| `model` | `"gemini/gemini-2.5-flash"` | LiteLLM model string. |
| `deep` | `False` | When `True`, the LLM also returns `confidence` and `evidence` per section. |
| `allow_overlap` | `True` | When `True`, a page may appear in multiple sections. Set `False` to enforce one section per page. |
| `split_rules` | `""` | Optional freeform instruction overriding the default splitting logic prompt. |
| `pages` | `None` | Subset of 0-based page indices to send to the LLM. `None` means all pages. |
| `llm` | `None` | Pre-configured LLM adapter instance. Overrides `model`. |
| `llm_kwargs` | `None` | Extra keyword arguments forwarded to litellm. |

## `SplitResult`

```python
result.success              # True when no errors and at least one section was returned
result.input_path           # original file path
result.total_pages          # number of pages processed
result.model                # model used
result.page_map             # dict[str, list[int]] — section_name → sorted page indices (property)
result.sections             # dict[str, SectionResult] — full detail per section
result.sections["body"].pages       # list[int]
result.sections["body"].confidence  # "high" | "medium" | "low"  (deep mode only)
result.sections["body"].evidence    # str  (deep mode only)
result.usage                # {"prompt_tokens": ..., "completion_tokens": ..., "cost_usd": ...}
result.warnings             # out-of-range pages removed, etc.
result.errors               # empty on success
```

`result.page_map` is a convenience property that returns plain `dict[str, list[int]]` with
pages sorted ascending. Use `result.sections` when you need confidence or evidence.

## Deep mode

Pass `deep=True` to request an evidence statement and confidence level for each section:

```python
result = split_document("contract.pdf", ContractSections, deep=True)

for name, section in result.sections.items():
    print(f"{name}: pages {section.pages} ({section.confidence})")
    print(f"  Evidence: {section.evidence}")
```

Confidence levels are `"high"`, `"medium"`, or `"low"`. Evidence is a one-sentence
explanation from the LLM of why those pages were assigned to the section.

## No-overlap mode

By default a page may appear in more than one section (e.g. a transition page with both
the last clause and the first exhibit). Pass `allow_overlap=False` to enforce exclusive
assignment:

```python
result = split_document("contract.pdf", ContractSections, allow_overlap=False)
```

## Custom split rules

Override the LLM's default splitting logic with a freeform instruction:

```python
result = split_document(
    "report.pdf",
    ReportSections,
    split_rules="Each chapter starts at a page with a heading in all-caps. "
                "Assign appendix pages to 'appendices' only.",
)
```

## Processing a page subset

Send only a subset of pages to the LLM, useful for large documents when you already know
which part contains the sections of interest:

```python
result = split_document("large-contract.pdf", ContractSections, pages=list(range(10, 40)))
```

The returned page indices are still the original 0-based document page numbers.

## Async usage

```python
from docuflow import split_document_async

result = await split_document_async("contract.pdf", ContractSections, deep=True)
```

## In a pipeline

Use the result's `page_map` to feed targeted extraction:

```python
from docuflow import extract, split_document

split = split_document("contract.pdf", ContractSections)
exhibit_pages = split.page_map.get("exhibits", [])

# Extract only from exhibit pages
extraction = await extract(
    "contract.pdf",
    schema=ExhibitSchema,
    pages=exhibit_pages,   # if your parser supports page selection
)
```

## MCP tool

```python
split_document(
    file_path: str,
    sections: str,          # JSON array: [{"name": "...", "description": "..."}]
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: str = "",        # comma-separated 0-based page indices; empty = all
) -> str                    # SplitResult JSON
```

## How it works

1. **Parse**: page text is extracted via pdfplumber (one call per page, no LLM).
2. **Prompt**: a single structured LLM call receives all page texts (truncated at 3 000
   chars each) plus the section descriptions and any custom rules.
3. **Structured output**: litellm's `response_format` parameter is used so the LLM returns
   valid JSON directly; no regex parsing.
4. **Validation**: out-of-range page indices returned by the LLM are stripped and reported
   as warnings.

## Limits

- Only PDF documents are supported in v1; DOCX splitting requires a different text
  extraction path.
- Very long documents may hit context limits; use `pages=` to restrict the range sent to
  the LLM, or choose a model with a larger context window.
- The LLM may assign pages to zero or multiple sections depending on document content and
  `allow_overlap` setting.
