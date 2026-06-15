from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from docuflow.documents.models import BoundingBox


class Comment(BaseModel):
    page_number: int | None = None
    author: str = ""
    date: str = ""
    text: str = ""
    bbox: BoundingBox | None = None


class Highlight(BaseModel):
    page_number: int | None = None
    subtype: Literal["Highlight", "Underline", "StrikeOut", "Squiggly", "Ink"] = "Highlight"
    color: str = ""
    text: str = ""
    bbox: BoundingBox | None = None


class Hyperlink(BaseModel):
    page_number: int | None = None
    url: str = ""
    text: str = ""
    bbox: BoundingBox | None = None


class Signature(BaseModel):
    page_number: int | None = None
    field_name: str = ""
    signer: str = ""
    date: str = ""
    signed: bool = False
    bbox: BoundingBox | None = None


class Revision(BaseModel):
    """DOCX-only: tracked insertion or deletion."""

    revision_type: Literal["insertion", "deletion"] = "insertion"
    author: str = ""
    date: str = ""
    text: str = ""


class DocumentMetadataResult(BaseModel):
    input_path: str
    comments: list[Comment] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    hyperlinks: list[Hyperlink] = Field(default_factory=list)
    signatures: list[Signature] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def has_metadata(self) -> bool:
        return bool(
            self.comments
            or self.highlights
            or self.hyperlinks
            or self.signatures
            or self.revisions
        )
