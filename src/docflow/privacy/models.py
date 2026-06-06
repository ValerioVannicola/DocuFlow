from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, ConfigDict, Field

from docflow.documents.models import BoundingBox


class AnonymizationMode(str, enum.Enum):
    REDACT = "redact"
    MASK = "mask"
    PSEUDONYMIZE = "pseudonymize"
    HASH = "hash"


class PrivacyFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_type: str
    start: int
    end: int
    text: str
    score: float = 0.0
    page_number: int | None = None
    bbox: BoundingBox | None = None


class TokenMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str
    original: str
    entity_type: str


class AnonymizedText(BaseModel):
    text: str
    mapping_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    findings: list[PrivacyFinding] = Field(default_factory=list)
    mappings: list[TokenMapping] = Field(default_factory=list)


class AnonymizationResult(BaseModel):
    document_id: str
    mapping_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anonymized_text: str = ""
    findings: list[PrivacyFinding] = Field(default_factory=list)
    token_mappings: list[TokenMapping] = Field(default_factory=list)
    mode: str = "pseudonymize"
    page_results: list[AnonymizedText] = Field(default_factory=list)
    risk_score: float = 0.0
