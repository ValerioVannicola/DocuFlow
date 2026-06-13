# Schemas, Templates, And Discovery

DocuFlow extracts into a Pydantic schema. Users can provide that schema directly in Python,
load it from a YAML template, or ask an LLM to discover a schema from a representative document.

## Python Schemas

Use Pydantic `BaseModel` classes for the strongest typing and editor support.

```python
from pydantic import BaseModel, Field

class Invoice(BaseModel):
    supplier_name: str = Field(description="Name of the supplier")
    invoice_number: str = Field(description="Invoice reference number")
    invoice_date: str = Field(description="Date of the invoice")
    total: float = Field(description="Total amount including tax")
    currency: str = Field(default="EUR", description="Currency code")
```

Pass the class to any extraction API:

```python
from docuflow import extract

result = extract("invoice.pdf", schema=Invoice)
```

Schema rules:

- Field names should be snake_case.
- Field descriptions are important; extraction prompts use them to understand what to extract.
- Required Pydantic fields are treated as required extraction targets.
- Optional/defaulted fields are allowed and may come back as `None`.
- Nested Pydantic models and list fields can be used directly in Python schemas.

## YAML Templates

YAML templates are portable schema definitions. They can be used by Python, CLI workflows,
routers, serving, and Docker deployments.

Example:

```yaml
name: invoice
version: "1.0"
description: Standard invoice extraction schema
fields:
  supplier_name:
    type: str
    required: true
    description: Name of the supplier
  total:
    type: float
    required: true
    description: Total amount including tax
  currency:
    type: str
    default: EUR
    description: Currency code
```

Load it:

```python
from docuflow.templates import load_template

Invoice = load_template("invoice")
```

## Template Field Options

Each field entry supports:

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `type` | `str` | `"str"` | Field type. See supported types below. |
| `required` | `bool` | `False` | If true, the generated Pydantic field is required. |
| `default` | Any | Required sentinel or `None` | Default value. If omitted and not required, default becomes `None`. |
| `description` | `str` | `""` | Field description passed to Pydantic and the extraction prompt. |
| `item_type` | `str` | `"str"` | For `type: list`, scalar type of list items. |
| `item_fields` | `dict` | Not set | For `type: list`, build a list of nested object items. |
| `fields` | `dict` | `{}` | For `type: object`, nested object field definitions. |

Supported scalar types:

| YAML value | Python type |
| --- | --- |
| `str`, `string` | `str` |
| `int`, `integer` | `int` |
| `float`, `number` | `float` |
| `bool`, `boolean` | `bool` |
| `date` | `datetime.date` |
| `datetime` | `datetime.datetime` |

Unsupported or unknown type strings fall back to `str`.

## Required And Optional Behavior

Required field:

```yaml
invoice_number:
  type: str
  required: true
```

Generated shape:

```python
invoice_number: str
```

Optional field:

```yaml
purchase_order:
  type: str
  required: false
```

Generated shape:

```python
purchase_order: str | None = None
```

Defaulted field:

```yaml
currency:
  type: str
  default: EUR
```

Generated shape:

```python
currency: str = "EUR"
```

## Structured Template Fields

### List Of Scalars

```yaml
tags:
  type: list
  item_type: str
  description: Labels found on the document
```

Generates `list[str]`.

### List Of Objects

```yaml
line_items:
  type: list
  description: Invoice line items
  item_fields:
    description:
      type: str
      required: true
    quantity:
      type: float
      required: true
    unit_price:
      type: float
      required: false
    total:
      type: float
      required: true
```

Generates a list of dynamically created Pydantic item models.

### Nested Object

```yaml
supplier:
  type: object
  fields:
    name:
      type: str
      required: true
    vat_number:
      type: str
      required: false
```

Generates a nested Pydantic model.

## Template Search Order

`TemplateRegistry` searches in this order by default:

1. Project-local templates: `docuflow_templates/`
2. User templates: `~/.docuflow/templates/`
3. Built-in templates inside the package.

Project templates override user and built-in templates with the same file stem.

Supported file extensions: `.yaml`, `.yml`.

Built-in templates include:

- `invoice`
- `contract`
- `receipt`

The project may also contain a local `custom` template if present in `docuflow_templates/`.

## `TemplateRegistry`

Import:

```python
from docuflow.templates import TemplateRegistry
```

Constructor:

```python
TemplateRegistry(search_dirs: list[pathlib.Path] | None = None)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `search_dirs` | `None` | Custom ordered template directories. If omitted, uses project, user, built-in order. |

### `load_raw()`

```python
registry.load_raw(name: str) -> dict
```

Loads the YAML template as a Python dict. Raises `FileNotFoundError` if the template name
is not found and `ValueError` if the file content is not a dict.

### `load()`

```python
registry.load(name: str) -> type[pydantic.BaseModel]
```

Loads a template and converts it to a Pydantic model class.

### `list_templates()`

```python
registry.list_templates() -> list[TemplateInfo]
```

Returns all visible templates after applying search-order shadowing.

### `save_template()`

```python
registry.save_template(
    name: str,
    template_data: dict,
    user_dir: bool = True,
) -> pathlib.Path
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `name` | Required | File stem for the template. |
| `template_data` | Required | Dict to dump as YAML. |
| `user_dir` | `True` | If true, saves to `~/.docuflow/templates/`; otherwise saves to `docuflow_templates/`. |

Returns the saved path.

## `TemplateInfo`

Dataclass returned by `list_templates()`:

| Field | Type | Description |
| --- | --- | --- |
| `name` | `str` | Template name from YAML or file stem. |
| `version` | `str` | Template version from YAML, default `"0.0"`. |
| `description` | `str` | Template description. |
| `source` | `str` | `"project"`, `"user"`, or `"builtin"`. |
| `path` | `Path` | Template file path. |

## Convenience Functions

### `load_template()`

```python
from docuflow.templates import load_template

Schema = load_template("invoice")
```

Signature:

```python
load_template(name: str) -> type[pydantic.BaseModel]
```

Uses the default registry.

### `list_templates()`

```python
from docuflow.templates import list_templates

templates = list_templates()
```

Signature:

```python
list_templates() -> list[TemplateInfo]
```

Uses the default registry.

## Low-Level YAML Conversion

Import:

```python
from docuflow.templates.loader import yaml_to_pydantic
```

Signature:

```python
yaml_to_pydantic(template_data: dict) -> type[pydantic.BaseModel]
```

Expected input shape:

```python
{
    "name": "invoice",
    "fields": {
        "total": {
            "type": "float",
            "required": True,
            "description": "Total amount",
        }
    },
}
```

## Schema Discovery

Schema discovery asks an LLM to inspect a document and propose extractable fields.

```python
from docuflow import discover_schema

discovery = discover_schema("invoice.pdf")
Invoice = discovery.schema_class
result = extract("invoice.pdf", schema=Invoice)
```

### `discover_schema()`

Top-level sync import:

```python
from docuflow import discover_schema
```

Actual sync implementation: `discover_schema_sync()`.

Signature:

```python
discover_schema(
    path: str,
    llm: LLMAdapter | None = None,
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
) -> DiscoveryResult
```

### `discover_schema_async()`

```python
from docuflow import discover_schema_async

discovery = await discover_schema_async("invoice.pdf")
```

Async signature:

```python
await discover_schema_async(
    path: str,
    llm: LLMAdapter | None = None,
    model: str = "openai/gpt-4o",
    parser: str = "pdfplumber",
) -> DiscoveryResult
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `path` | Required | Document path to inspect. |
| `llm` | `None` | Optional LLM adapter. If omitted, uses `LiteLLMAdapter(model=model)`. |
| `model` | `"openai/gpt-4o"` | Model for discovery when `llm` is not supplied. |
| `parser` | `"pdfplumber"` | Parser for reading text before discovery. Supported directly: `"pdfplumber"`, `"tesseract"`, `"docling"`, `"smart"`. |

Discovery reads up to the first 8000 characters of parsed document text.

## `DiscoveryResult`

Fields:

| Field | Type | Description |
| --- | --- | --- |
| `document_type` | `str` | Suggested document type, such as `"invoice"`. |
| `description` | `str` | One-line description of the document. |
| `fields` | `list[DiscoveredField]` | Suggested extracted fields. |
| `schema_class` | `Any` | Generated Pydantic model class. |
| `yaml_template` | `str` | Generated YAML template text. |

## `DiscoveredField`

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | Required | Snake-case field name. |
| `type` | `str` | `"str"` | Suggested type. |
| `required` | `bool` | `True` | Whether the field appears required. |
| `description` | `str` | `""` | Field description. |

Discovery type mapping:

| Discovery type | Generated Python type |
| --- | --- |
| `str`, `string` | `str` |
| `float` | `float` |
| `int`, `integer` | `int` |
| `bool`, `boolean` | `bool` |
| `date`, `datetime` | `str` |
| `list[str]`, `list` | `list[str]` |

The generated YAML template currently preserves only scalar YAML types `str`, `int`, `float`,
`bool`, and `date`; other discovered types are written as `str`.

## CLI Template Commands

```bash
docuflow templates list
docuflow templates show invoice
docuflow templates init invoice
```

Options:

| Command | Parameters |
| --- | --- |
| `templates list` | No parameters. Lists available templates. |
| `templates show NAME` | `NAME`: template name. Prints YAML. |
| `templates init NAME --dir TARGET_DIR` | Copies a built-in template into `TARGET_DIR` or `docuflow_templates/` by default. |

## CLI Schema Loading

CLI commands that accept `--schema` can load:

- Built-in or registered template names, such as `invoice`.
- Dotted Python paths, depending on `docuflow.cli.utils.load_schema()`.

Example:

```bash
docuflow extract invoice.pdf --schema invoice --output result.json
```
