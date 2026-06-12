from __future__ import annotations

import enum
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def to_relative(self, page_width: float, page_height: float) -> BoundingBox:
        """Normalize to 0-1 coordinates relative to the page dimensions.

        Useful for overlaying highlights on a page rendered at any DPI:
        multiply by the rendered image's pixel dimensions.
        """
        if page_width <= 0 or page_height <= 0:
            return self
        return BoundingBox(
            x0=self.x0 / page_width,
            y0=self.y0 / page_height,
            x1=self.x1 / page_width,
            y1=self.y1 / page_height,
        )


class PageRect(BaseModel):
    """A highlight rectangle tied to a page — one segment of a text span.

    A span matching text across lines or pages carries one PageRect per
    (page, line) segment, the way PDF viewers draw multi-line selections.
    """

    model_config = ConfigDict(frozen=True)

    page_number: int
    bbox: BoundingBox


class BlockType(str, enum.Enum):
    TEXT = "text"
    TITLE = "title"
    TABLE = "table"
    IMAGE = "image"
    HEADER = "header"
    FOOTER = "footer"
    LIST_ITEM = "list_item"
    FORMULA = "formula"
    PARAGRAPH = "paragraph"


class Word(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = None


class Block(BaseModel):
    """A line-level unit of text on a page.

    OCR-based parsers populate `words` (one entry per recognized word, each
    with its own confidence) and set `confidence` to the aggregate for the
    line. Native parsers (pdfplumber) fill `words` too but leave `confidence` None.
    """

    model_config = ConfigDict(frozen=True)

    block_id: str
    block_type: BlockType = BlockType.TEXT
    text: str = ""
    bbox: BoundingBox | None = None
    confidence: float | None = None
    words: list[Word] = Field(default_factory=list)


class Page(BaseModel):
    """A parsed page. All bboxes share one coordinate space: top-left origin,
    in `unit` units, consistent with `width`/`height`.

    The canonical unit is PDF points ("pt", 72 per inch) — parsers convert
    when they can (rendered-image pixels via DPI, Azure inches). "px" marks
    providers whose physical page size is unknown (e.g. Google Document AI);
    rects there are still consistent with width/height, so
    `BoundingBox.to_relative()` works regardless.
    """

    page_number: int
    width: float | None = None
    height: float | None = None
    unit: str = "pt"
    blocks: list[Block] = Field(default_factory=list)
    tables: list = Field(default_factory=list)
    text: str = ""
    image_path: str | None = None

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def table_count(self) -> int:
        return len(self.tables)


class DocumentMetadata(BaseModel):
    file_name: str
    file_path: str
    file_size: int = 0
    file_hash: str = ""
    mime_type: str = ""
    page_count: int | None = None
    source_uri: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    extra: dict = Field(default_factory=dict)


class Document(BaseModel):
    id: str
    metadata: DocumentMetadata
    pages: list[Page] = Field(default_factory=list)
    raw_text: str = ""
    status: str = "ingested"

    @classmethod
    async def from_file(cls, path: str | Path) -> Document:
        from docflow.ingestion.local import ingest_file

        return await ingest_file(path)

    @classmethod
    def from_file_sync(cls, path: str | Path) -> Document:
        from docflow._sync import run_sync

        return run_sync(cls.from_file(path))
