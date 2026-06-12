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
    page_number: int
    width: float | None = None
    height: float | None = None
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
