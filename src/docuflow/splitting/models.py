from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentSection(BaseModel):
    """One section definition, used when passing sections as a list instead of a schema class."""

    name: str = Field(description="Section identifier (snake_case recommended)")
    description: str = Field(description="Natural-language description of what belongs here")


class SectionResult(BaseModel):
    """The LLM's assignment for one section."""

    pages: list[int] = Field(default_factory=list, description="0-based page indices assigned to this section")
    confidence: Literal["high", "medium", "low"] = "high"
    evidence: str = ""


class SplitResult(BaseModel):
    """Result of :func:`split_document`."""

    input_path: str
    sections: dict[str, SectionResult] = Field(default_factory=dict)
    total_pages: int = 0
    model: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def page_map(self) -> dict[str, list[int]]:
        """Simple dict: section_name → sorted list of 0-based page indices."""
        return {name: sorted(sr.pages) for name, sr in self.sections.items()}

    @property
    def success(self) -> bool:
        return not self.errors and bool(self.sections)


# ---------------------------------------------------------------------------
# Internal LLM response schemas — not exported
# ---------------------------------------------------------------------------

class _SimpleSectionOutput(BaseModel):
    pages: list[int] = Field(default_factory=list)


class _DeepSectionOutput(BaseModel):
    pages: list[int] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "high"
    evidence: str = ""


class _SimpleSplitResponse(BaseModel):
    sections: dict[str, _SimpleSectionOutput]


class _DeepSplitResponse(BaseModel):
    sections: dict[str, _DeepSectionOutput]
