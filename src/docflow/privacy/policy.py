from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from docflow.privacy.models import AnonymizationMode


class PrivacyPolicy(BaseModel):
    anonymize_before_llm: bool = True
    mode: AnonymizationMode = AnonymizationMode.PSEUDONYMIZE
    reversible: bool = True
    provider: Any = None
    entities: list[str] = Field(
        default_factory=lambda: [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "IBAN_CODE",
            "CREDIT_CARD",
            "LOCATION",
            "DATE_TIME",
        ]
    )
    fail_closed: bool = True
    score_threshold: float = 0.35
    log_scrubbing: bool = True
    mapping_store: Any = None

    @model_validator(mode="after")
    def _validate_reversible(self) -> PrivacyPolicy:
        if self.reversible and self.mode != AnonymizationMode.PSEUDONYMIZE:
            raise ValueError(
                f"reversible=True requires mode='pseudonymize', got mode='{self.mode.value}'"
            )
        return self
