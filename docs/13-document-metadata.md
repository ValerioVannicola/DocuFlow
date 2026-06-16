# Document Metadata Extraction

DocuFlow can extract document-level metadata that lives outside the main text content:
PDF annotations (comments, highlights, hyperlinks, signatures) and DOCX structural
elements (comments, tracked changes, hyperlinks, highlighted runs).

Requires no extra install beyond `docuflow[forms]` for PDF (uses pypdf) or the standard
library for DOCX (uses stdlib `zipfile` + `xml.etree`).

## Public API

```python
from docuflow import extract_metadata, extract_metadata_async
from docuflow.metadata import (
    DocumentMetadataResult,
    Comment,
    Highlight,
    Hyperlink,
    Signature,
    Revision,
)
```

## `extract_metadata()`

```python
extract_metadata(path: str | Path) -> DocumentMetadataResult
```

`extract_metadata_async` is the async version.

```python
from docuflow import extract_metadata

result = extract_metadata("contract.pdf")

result.success          # True when no errors
result.has_metadata     # True when at least one item was found
result.comments         # list[Comment]
result.highlights       # list[Highlight]
result.hyperlinks       # list[Hyperlink]
result.signatures       # list[Signature]
result.revisions        # list[Revision]  (DOCX only)
result.warnings         # non-fatal issues (e.g. a malformed annotation)
result.errors           # fatal errors (file not found, missing dependency)
```

Dispatches automatically on file extension: `.docx` → DOCX extractor;
everything else → PDF extractor. Legacy `.doc` (binary Word) is not supported
and returns a result with an error explaining to convert to `.docx` or PDF.

`extract_metadata_async` runs the blocking extractor in a worker thread, so it is
safe to call from an event loop without stalling it.

## `DocumentMetadataResult`

| Attribute | Type | Description |
| --- | --- | --- |
| `result.input_path` | `str` | Original file path. |
| `result.success` | `bool` | `True` when `errors` is empty. |
| `result.has_metadata` | `bool` | `True` when any list is non-empty. |
| `result.comments` | `list[Comment]` | Annotation comments / reviewer notes. |
| `result.highlights` | `list[Highlight]` | Highlighted / underlined / struck-out regions. |
| `result.hyperlinks` | `list[Hyperlink]` | Links to external URLs or internal bookmarks. |
| `result.signatures` | `list[Signature]` | Signature fields (PDF only). |
| `result.revisions` | `list[Revision]` | Tracked insertions and deletions (DOCX only). |
| `result.warnings` | `list[str]` | Non-fatal extraction issues. |
| `result.errors` | `list[str]` | Fatal errors. Empty on success. |

## Model Reference

### `Comment`

| Field | Type | Description |
| --- | --- | --- |
| `page_number` | `int \| None` | 0-based page index. `None` for DOCX comments (no page binding). |
| `author` | `str` | Reviewer name. |
| `date` | `str` | ISO-8601 date string or PDF date string (`D:YYYYMMDDHHmmss`). |
| `text` | `str` | Comment body text. |
| `bbox` | `BoundingBox \| None` | Location on the page (PDF only). |

### `Highlight`

| Field | Type | Description |
| --- | --- | --- |
| `page_number` | `int \| None` | 0-based page index. |
| `subtype` | `str` | `"Highlight"`, `"Underline"`, `"StrikeOut"`, `"Squiggly"`, `"Ink"`. |
| `color` | `str` | Hex color string, e.g. `"#ffff00"`. Empty when unknown. |
| `text` | `str` | Reviewer's note on the highlight (from `/Contents`). **Not** the highlighted words — see Limits. |
| `bbox` | `BoundingBox \| None` | Bounding rectangle of the highlighted region. |

### `Hyperlink`

| Field | Type | Description |
| --- | --- | --- |
| `page_number` | `int \| None` | 0-based page index (PDF only). |
| `url` | `str` | Full URL, `internal:<dest>` for PDF GoTo actions, `#bookmark:<name>` for DOCX anchors. |
| `text` | `str` | Link display text (DOCX only — PDF link text is not stored in the annotation). |
| `bbox` | `BoundingBox \| None` | Clickable region (PDF only). |

### `Signature`

PDF only.

| Field | Type | Description |
| --- | --- | --- |
| `page_number` | `int \| None` | 0-based page index. |
| `field_name` | `str` | PDF field name (`/T`). |
| `signer` | `str` | Signer name from the signature value object (`/Name`). Empty if unsigned. |
| `date` | `str` | Signing date from the value object (`/M`). Empty if unsigned. |
| `signed` | `bool` | `True` when the field contains a signature value (`/V`). |
| `bbox` | `BoundingBox \| None` | Field location on the page. |

### `Revision`

DOCX only.

| Field | Type | Description |
| --- | --- | --- |
| `revision_type` | `"insertion" \| "deletion"` | Track-change type. |
| `author` | `str` | Author of the change. |
| `date` | `str` | ISO-8601 date string. |
| `text` | `str` | The inserted or deleted text. |

## PDF extraction details

DocuFlow reads the `/Annots` array on each PDF page. Each annotation object's `/Subtype`
determines its category:

| PDF subtype | Extracted as |
| --- | --- |
| `/Text`, `/FreeText`, `/Popup` | `Comment` |
| `/Highlight`, `/Underline`, `/StrikeOut`, `/Squiggly`, `/Ink` | `Highlight` |
| `/Link` | `Hyperlink` — URI action → `url`; GoTo action → `internal:<dest>` |
| `/Widget` with `/FT /Sig` | `Signature` |

Bounding boxes are converted from PDF bottom-left origin (`[llx lly urx ury]`) to
DocuFlow's top-left origin using `page_height - y`.

## DOCX extraction details

DocuFlow reads the DOCX ZIP directly (no python-docx required):

| Source | Extracted as |
| --- | --- |
| `word/comments.xml` — `w:comment` elements | `Comment` |
| `word/document.xml` — `w:hyperlink` elements + `word/_rels/document.xml.rels` | `Hyperlink` (URL resolved from relationship map) |
| `word/document.xml` — `w:ins` elements | `Revision(revision_type="insertion")` |
| `word/document.xml` — `w:del` elements | `Revision(revision_type="deletion")` |
| `word/document.xml` — `w:rPr/w:highlight` run properties | `Highlight` (color mapped from WML color names to hex) |

## Limits

- **Highlight text content**: `Highlight.text` is the reviewer's note from `/Contents`, not
  the actual highlighted words. Extracting highlighted words from a PDF requires cross-referencing
  the `/QuadPoints` annotation attribute against the PDF text layer. This is not implemented.
  On scanned PDFs there is no text layer, so highlighted word extraction is not possible
  regardless.
- **Scanned PDFs**: annotation metadata (bbox, color, author, date) is extracted correctly
  because PDF annotations are stored independently of page content. Only `text` is empty.
- **Signatures**: DocuFlow detects signature fields and whether they are signed. It does not
  validate cryptographic signatures.
- **DOCX signatures**: Word digital signature infrastructure (`_xmlsignatures/`) is not parsed.
- **Embedded comments** in DOCX (comment replies, threaded comments) are treated as
  independent `Comment` entries.
