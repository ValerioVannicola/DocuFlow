from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ValidationError(BaseModel):
    field_name: str
    rule_name: str
    message: str
    severity: str = "error"  # "error" or "warning"


@runtime_checkable
class Validator(Protocol):
    def validate(self, result: object) -> list[ValidationError]: ...
