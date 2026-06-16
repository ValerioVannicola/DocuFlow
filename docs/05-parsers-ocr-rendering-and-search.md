# Parsers, OCR, Rendering, And Search

This file documents how DocuFlow reads documents, normalizes geometry, renders pages, searches
text, and creates screenshots/highlight images.

## Parser Contract

All parser classes implement the `Parser` protocol:

```python
from docuflow.parsing.base import Parser

async def parse(document: Document) -> Document
```

The parser receives an ingested `Document` whose metadata points to the source file and returns
the same document populated with:

- `pages`
- `raw_text`
- `metadata.page_count`
- `status = "parsed"`

Every parser emits line-level `Block` objects. OCR parsers attach per-word `Word` objects with
confidence where available.

## High-Level Parser Selection

`DocumentPipeline(parser=...)` accepts strings, config dicts, or parser objects.

| Parser | Best for | Confidence | Tables | Install |
| --- | --- | --- | --- | --- |
| `"auto"` | Source-aware default: text files skip parsing, images use OCR, PDFs use native/smart parsing, Office files use Docling. | Depends on selected path. | Depends on selected path. | Depends on input type. |
| `"pdfplumber"` | Native/digital PDFs with text layers. | No OCR confidence. | No first-class tables. | `docuflow[pdf]` |
| `"tesseract"` | Scanned PDFs/images using local OCR. | Word and line confidence. | No first-class tables. | `docuflow[pdf,ocr]` plus system `tesseract` |
| `"docling"` | Complex layouts, headings, lists, tables. | OCR confidence when Docling OCR fires. | Yes. | `docuflow[docling]` |
| `"smart"` | Mixed native/scanned PDFs. | Only OCR pages have confidence. | No first-class tables. | `docuflow[pdf,ocr]` plus system `tesseract` |
| `"azure-di"` | Azure Document Intelligence cloud OCR. | Word and derived line confidence. | Current mapper emits text blocks. | `docuflow[azure]` |
| `"textract"` | AWS Textract OCR. | Word and line confidence. | Current parser uses DetectDocumentText text output. | `docuflow[aws,pdf]` |
| `"google-docai"` | Google Document AI OCR. | Token and line confidence. | Current mapper emits text blocks. | `docuflow[gcp]` |
| `None` / `"none"` | Parserless mode. Text-like inputs are already parsed by ingestion; PDF/image inputs can be read by vision/hybrid. | N/A. | N/A. | Depends on extraction type. |

Text-like inputs (`txt`, `md`, `html`, `csv`, `json`, `xml`, `eml`) are normalized during
ingestion into a one-page `Document` with `status="parsed"`, so no parser is required for
text extraction. Image inputs can be rendered as one-page documents for vision or OCR.

## Parser Config Dicts

```python
from docuflow import DocumentPipeline

pipeline = DocumentPipeline(
    parser={"type": "smart", "languages": ["eng"], "dpi": 300},
)
```

Supported configs:

```python
{"type": "auto"}
{"type": "pdfplumber"}
{"type": "tesseract", "languages": ["eng"], "dpi": 300, "preprocess": []}
{"type": "docling"}
{"type": "smart", "languages": ["eng"], "dpi": 300, "min_text_length": 20}
{"type": "azure-di", "endpoint": "...", "key": "...", "model": "prebuilt-read"}
{"type": "textract", "region": "eu-west-1", "dpi": 200}
{"type": "google-docai", "project": "p", "location": "us", "processor_id": "x"}
```

## Coordinate Convention

DocuFlow uses page-local coordinates:

- Origin: top-left.
- Canonical PDF coordinate unit: points (`"pt"`, 72/inch).
- `pdfplumber`, Tesseract, Textract, and Azure PDF output are converted to points where possible.
- Google Document AI and image inputs may keep `unit="px"` when physical page size is unknown.
- `Page.width`, `Page.height`, and all bboxes on a page always use the same unit.
- Use `BoundingBox.to_relative(page.width, page.height)` to render overlays at any DPI.

```python
rel = bbox.to_relative(page.width, page.height)
pixel_rect = (
    rel.x0 * rendered_width,
    rel.y0 * rendered_height,
    rel.x1 * rendered_width,
    rel.y1 * rendered_height,
)
```

## Parser Classes

### `PdfplumberParser`

Import:

```python
from docuflow.parsing.pdfplumber_parser import PdfplumberParser
```

Constructor:

```python
PdfplumberParser()
```

Method:

```python
await parser.parse(document: Document) -> Document
```

Behavior:

- Reads native PDF text layer with `pdfplumber`.
- Groups words into visual line-level blocks.
- Adds image blocks for page images.
- Populates word bounding boxes.
- Leaves word/block confidence as `None` because no OCR ran.

### `TesseractParser`

Import:

```python
from docuflow.parsing.tesseract_parser import TesseractParser
```

Constructor:

```python
TesseractParser(
    languages: list[str] | None = None,
    dpi: int = DEFAULT_DPI,
    preprocess_steps: list[str] | None = None,
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `languages` | `["eng"]` | Tesseract language codes. Combined as `"eng+ita"` when calling Tesseract. |
| `dpi` | `DEFAULT_DPI` | Render DPI used before OCR. Higher improves OCR at higher cost. |
| `preprocess_steps` | `None` | Optional OCR preprocessing steps passed to `TesseractOCR`. |

Behavior:

- Renders all pages locally.
- Runs Tesseract OCR concurrently.
- Converts rendered pixel coordinates back to PDF points using `72 / dpi`.
- Populates words, bboxes, and confidence.

Requires the `pytesseract` Python package and the system `tesseract` executable.

#### Locating the `tesseract` binary

`pytesseract` is only a wrapper — it shells out to the native `tesseract`
program, which is a separate install:

- macOS: `brew install tesseract`
- Debian/Ubuntu: `apt-get install tesseract-ocr`
- Windows: install from https://github.com/UB-Mannheim/tesseract/wiki

If the binary is not on your `PATH` (common on Windows, where the installer
does not add it), set the `DOCUFLOW_TESSERACT_CMD` environment variable to its
full path instead of editing code:

```bash
export DOCUFLOW_TESSERACT_CMD="C:\Users\you\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
```

When the binary cannot be found, DocuFlow raises an `OCRError` that explains
both of these fixes.

### `SmartParser`

Import:

```python
from docuflow.parsing.smart_parser import SmartParser
```

Constructor:

```python
SmartParser(
    ocr_languages: list[str] | None = None,
    dpi: int = DEFAULT_DPI,
    min_text_length: int = 20,
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `ocr_languages` | `["eng"]` | Tesseract language codes for fallback OCR. |
| `dpi` | `DEFAULT_DPI` | Render DPI for fallback OCR pages. |
| `min_text_length` | `20` | Minimum text length threshold used by the parser instance. |

Behavior:

1. Parses with `PdfplumberParser`.
2. Detects pages that appear scanned, sparse, image-heavy, or garbled.
3. OCRs only those pages with Tesseract.
4. Replaces low-quality native pages with OCR pages.

Use this as the default for mixed PDF streams.

### `DoclingParser`

Import:

```python
from docuflow.parsing.docling_parser import DoclingParser
```

Constructor:

```python
DoclingParser()
```

Behavior:

- Uses Docling `DocumentConverter`.
- Converts Docling layout labels into DocuFlow block types.
- Extracts tables as first-class `Table` objects.
- Uses Docling markdown export as `document.raw_text`.
- Attaches OCR word confidence to blocks when Docling exposes OCR cells.
- Native Docling parses may have no OCR confidence by design.

Docling block label mapping includes:

| Docling label | DocuFlow `BlockType` |
| --- | --- |
| `title`, `section_header` | `TITLE` |
| `text` | `TEXT` |
| `paragraph` | `PARAGRAPH` |
| `list_item` | `LIST_ITEM` |
| `picture`, `chart` | `IMAGE` |
| `formula` | `FORMULA` |
| `page_header` | `HEADER` |
| `page_footer` | `FOOTER` |
| `caption`, `footnote`, `code`, `reference` | `TEXT` |

### `AzureDocumentIntelligenceParser`

Import:

```python
from docuflow.parsing.azure_di import AzureDocumentIntelligenceParser
```

Constructor:

```python
AzureDocumentIntelligenceParser(
    endpoint: str | None = None,
    key: str | None = None,
    model: str = "prebuilt-read",
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `endpoint` | Env `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Azure Document Intelligence endpoint. |
| `key` | Env `AZURE_DOCUMENT_INTELLIGENCE_KEY` | Azure key. |
| `model` | `"prebuilt-read"` | Azure model/deployment name passed to `begin_analyze_document()`. |

Behavior:

- Sends the original file to Azure; no local rendering needed.
- Converts Azure page/line/word output into DocuFlow pages.
- Azure PDF coordinates in inches are converted to points.
- Image coordinates are kept in pixels with `unit="px"`.
- Line confidence is derived from word confidences.

### `TextractParser`

Import:

```python
from docuflow.parsing.textract import TextractParser
```

Constructor:

```python
TextractParser(region_name: str | None = None, dpi: int = DEFAULT_DPI)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `region_name` | `None` | AWS region for the Textract client. If omitted, uses the default boto3 region. |
| `dpi` | `DEFAULT_DPI` | Render DPI before sending each page image to Textract. |

Behavior:

- Uses standard `boto3` credential resolution.
- Renders pages locally and sends each page image to `DetectDocumentText`.
- Saves JPEG page bytes to stay under the synchronous Textract file-size limit.
- Converts relative Textract geometry into page-space points.
- Textract confidences are converted from 0-100 to 0-1.

### `GoogleDocumentAIParser`

Import:

```python
from docuflow.parsing.google_docai import GoogleDocumentAIParser
```

Constructor:

```python
GoogleDocumentAIParser(
    project: str | None = None,
    location: str | None = None,
    processor_id: str | None = None,
)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `project` | Env `GOOGLE_DOCAI_PROJECT` | Google Cloud project. |
| `location` | Env `GOOGLE_DOCAI_LOCATION` or `"us"` | Document AI processor location. |
| `processor_id` | Env `GOOGLE_DOCAI_PROCESSOR_ID` | Processor ID. |

Behavior:

- Sends the original file to Google Document AI.
- Uses application default credentials.
- Maps Document AI lines/tokens to DocuFlow blocks/words.
- Uses token and line layout confidence.
- Page units are `"pt"` when Document AI reports points, otherwise `"px"`.

## OCR Data

OCR-based parsers populate:

```python
word.text
word.bbox
word.confidence
block.confidence
```

Extraction later computes:

```python
result.ocr
field.ocr
```

Native parsers may leave OCR confidence as `None`; downstream code treats that as "no OCR ran"
rather than failure.

### OCR in vision and hybrid modes

`extraction_type="vision"` and `"hybrid"` do not use a parser, but they still
produce `result.ocr` and bounding boxes: the engine OCRs the rendered page
images in the background (`VisionExtractionEngine._enrich_document_with_ocr`) to
ground evidence. This needs an OCR engine (the native `tesseract` binary, or
`DOCUFLOW_TESSERACT_CMD`). When none is available the enrichment is skipped —
the run still completes, a warning is emitted, and `result.ocr` is `None` with
no bounding boxes. So OCR confidence is a function of *whether OCR ran*, not of
*which parser was selected*.

## Rendering And Screenshots

### `screenshot_pages()`

Import:

```python
from docuflow.screenshots import screenshot_pages
```

Signature:

```python
await screenshot_pages(
    file_path: str | pathlib.Path,
    output_dir: str | pathlib.Path | None = None,
    pages: list[int] | None = None,
    dpi: int = DEFAULT_DPI,
    format: str = "png",
) -> list[PageScreenshot]
```

### `screenshot_pages_sync()`

```python
from docuflow.screenshots import screenshot_pages_sync

shots = screenshot_pages_sync("doc.pdf", output_dir="./pages", dpi=200)
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | PDF path. |
| `output_dir` | `None` | If set, saves images there. If `None`, returns metadata without saving. |
| `pages` | `None` | Page indexes to render. `None` renders all pages. Page numbers are zero-based. |
| `dpi` | `DEFAULT_DPI` | Render DPI. |
| `format` | `"png"` | Output image format, usually `"png"` or `"jpeg"`. |

### `PageScreenshot`

Fields:

| Field | Type | Description |
| --- | --- | --- |
| `page_number` | `int` | Zero-based page index. |
| `width` | `int` | Rendered image width in pixels. |
| `height` | `int` | Rendered image height in pixels. |
| `file_path` | `str` | Saved file path, empty when no output directory was provided. |

## Field Highlight Rendering

### `highlight_fields()`

Import:

```python
from docuflow import highlight_fields
```

Signature:

```python
highlight_fields(
    file_path: str,
    result: ExtractionResult,
    output_dir: str | pathlib.Path = ".",
    fields: list[str] | None = None,
    dpi: int = 150,
    format: str = "png",
    color: str | tuple | None = None,
    show_labels: bool = True,
) -> list[str]
```

### `highlight_fields_async()`

```python
from docuflow import highlight_fields_async

paths = await highlight_fields_async("invoice.pdf", result, output_dir="./highlights")
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `file_path` | Required | Source PDF path. |
| `result` | Required | `ExtractionResult` whose field evidence or OCR spans have bboxes. |
| `output_dir` | `"."` | Directory where highlighted page images are saved. |
| `fields` | `None` | Field names to highlight. `None` highlights all fields. |
| `dpi` | `150` | Render DPI. |
| `format` | `"png"` | Output format. |
| `color` | `None` | `None` for yellow, `"auto"` for per-field colors, CSS color string, RGB tuple, or RGBA tuple. |
| `show_labels` | `True` | Draw field labels near boxes. |

Returns a list of saved image paths, one for each page that has evidence/ocr boxes.

## Search

### `search_document()`

Import:

```python
from docuflow.search import search_document
```

Signature:

```python
search_document(
    document: Document,
    query: str,
    case_sensitive: bool = False,
    context_chars: int = 50,
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.8,
) -> SearchResult
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `document` | Required | Parsed `Document`. |
| `query` | Required | Text phrase to find. Empty query returns zero hits. |
| `case_sensitive` | `False` | Case-sensitive matching when true. |
| `context_chars` | `50` | Number of surrounding page-text characters in hit context. |
| `fuzzy` | `False` | Enable approximate fallback when exact matching finds nothing. |
| `fuzzy_threshold` | `0.8` | Minimum SequenceMatcher ratio for fuzzy matches. |

Matching behavior:

- Exact matching is normalization-aware.
- Matches can span words, lines, blocks, and pages.
- With `find_all=True` internally, exact search returns all non-overlapping exact matches.
- Fuzzy mode returns the best fuzzy match when exact search fails.
- Page-text fallback is used for pages whose text is not represented in blocks.

### `SearchResult`

Fields:

| Field | Type | Description |
| --- | --- | --- |
| `query` | `str` | Original search query. |
| `total_hits` | `int` | Number of hits. |
| `hits` | `list[SearchHit]` | Hit details. |

### `SearchHit`

Fields:

| Field | Type | Description |
| --- | --- | --- |
| `text` | `str` | Matched text. |
| `page_number` | `int` | Page where the hit starts. |
| `block_id` | `str \| None` | First block ID when block-based matching found the hit. |
| `bbox` | `BoundingBox \| None` | Union rectangle for single-page matches. |
| `rects` | `list[PageRect]` | Per-page/line rectangles. |
| `match_ratio` | `float` | `1.0` exact; lower values are fuzzy. |
| `context` | `str` | Surrounding page text. |

## Low-Level Text Location

### `locate_text()`

Import:

```python
from docuflow.documents.locate import locate_text
```

Signature:

```python
locate_text(
    document: Document,
    query: str,
    *,
    case_sensitive: bool = False,
    fuzzy: bool = True,
    fuzzy_threshold: float = 0.8,
    hint_page: int | None = None,
    find_all: bool = False,
    stream: list | None = None,
) -> list[TextSpan]
```

Parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `document` | Required | Parsed document. |
| `query` | Required | Phrase/value to locate. |
| `case_sensitive` | `False` | Preserve case during normalization. |
| `fuzzy` | `True` | Allow fuzzy fallback for OCR-garbled text. |
| `fuzzy_threshold` | `0.8` | Minimum fuzzy match ratio. |
| `hint_page` | `None` | Prefer matches on this zero-based page. |
| `find_all` | `False` | Return all exact matches instead of best single match. |
| `stream` | `None` | Optional prebuilt word stream from `build_stream()` for repeated calls. |

### `build_stream()`

```python
from docuflow.documents.locate import build_stream

stream = build_stream(document)
spans = locate_text(document, "INV-001", stream=stream)
```

Signature:

```python
build_stream(document: Document, case_sensitive: bool = False) -> list
```

Use this when locating many phrases in the same document.

### `TextSpan`

Fields:

| Field | Type | Description |
| --- | --- | --- |
| `text` | `str` | Located text window. |
| `page_number` | `int` | Page where the span starts. |
| `bbox` | `BoundingBox \| None` | Union rectangle for single-page spans; `None` for cross-page spans. |
| `rects` | `list[PageRect]` | One rectangle per page/line segment. |
| `block_ids` | `list[str]` | Blocks contributing to the match. |
| `match_ratio` | `float` | Exact or fuzzy ratio. |
| `method` | `str` | `"exact"` or `"fuzzy"`. |
| `confidence` | `float \| None` | Minimum OCR word confidence in the span. |

## CLI Screenshot Command

```bash
docuflow screenshot file.pdf --output ./pages --dpi 200
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--output`, `-o` | Required | Output directory. |
| `--dpi` | `DEFAULT_DPI` | Render DPI. |
| `--pages` | `None` | Comma-separated zero-based page indexes, for example `0,1,2`. |
